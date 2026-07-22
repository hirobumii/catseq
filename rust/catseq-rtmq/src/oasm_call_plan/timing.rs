//! Algebraic and scheduled duration analysis for the Morphism DAG.

use catseq_core::exact_decimal::ExactDecimal;
use catseq_core::morphism_arena::{MorphismNodeKind, MorphismPayload};
use catseq_core::native_arenas::NativeArenas;

use super::arena_util::children_by_node;
use super::model::{AtomicLowering, LinkBindings, OasmCompileError, TargetProfile};
use super::value_eval::{
    atomic_bool_argument, eval_cycles, eval_duration_cycles, evaluate_numeric_values,
};

pub(super) struct TimingAnalysis {
    pub(super) evaluated_values: Vec<Result<ExactDecimal, OasmCompileError>>,
    pub(super) durations: Vec<u64>,
    pub(super) logical_durations: Vec<u64>,
}

pub(super) fn analyze_timing(
    program: &NativeArenas,
    target: &TargetProfile,
    link_bindings: &LinkBindings,
) -> Result<TimingAnalysis, OasmCompileError> {
    let arena = program.morphisms();
    let evaluated_values = evaluate_numeric_values(program, link_bindings);
    let mut durations = vec![0_u64; arena.nodes().len()];
    let mut logical_durations = vec![0_u64; arena.nodes().len()];
    for (index, node) in arena.nodes().iter().enumerate() {
        let payload = node
            .payload()
            .map(|payload| &arena.payloads()[payload.index()]);
        let (duration, logical_duration) = match node.kind() {
            MorphismNodeKind::Wait => match payload {
                Some(MorphismPayload::Wait { duration }) => {
                    let duration = eval_duration_cycles(
                        &evaluated_values,
                        *duration,
                        target.duration_quantization,
                    )
                    .map_err(|error| {
                        let source = &arena.provenance()[node.provenance().index()];
                        OasmCompileError::new(format!(
                            "invalid wait at {}:{}:{}: {error}",
                            source.owner(),
                            source.line(),
                            source.column()
                        ))
                    })?;
                    (duration, duration)
                }
                _ => unreachable!("validated arena has a Wait payload"),
            },
            MorphismNodeKind::Atomic => {
                match payload {
                    Some(payload @ MorphismPayload::Atomic { operation, .. }) => {
                        let operation = &arena.operations()[operation.index()];
                        let schema = target.operations.get(operation).ok_or_else(|| {
                            OasmCompileError::new(format!(
                                "Target Profile has no Atomic Schema for {operation}"
                            ))
                        })?;
                        let duration = if schema.lowering == AtomicLowering::RwgInitialize
                            && atomic_bool_argument(arena, payload, program, 1)
                        {
                            target.clock_hz.checked_div(1_000_000).ok_or_else(|| {
                                OasmCompileError::new("RWG hard-init delay is invalid")
                            })?
                        } else if let Some(duration) = schema.fixed_duration_cycles {
                            duration
                        } else if let Some(duration_argument) = schema.duration_argument {
                            let duration = arena
                                .payload_arguments(payload)
                                .map_err(|error| OasmCompileError::new(error.to_string()))?
                                .get(duration_argument)
                                .copied()
                                .ok_or_else(|| {
                                    let source = &arena.provenance()[node.provenance().index()];
                                    OasmCompileError::new(format!(
                                        "timed operation {operation} at {}:{}:{} requires a duration",
                                        source.owner(), source.line(), source.column()
                                    ))
                                })?;
                            eval_duration_cycles(
                                &evaluated_values,
                                duration,
                                target.duration_quantization,
                            )
                            .map_err(|error| {
                                OasmCompileError::new(format!(
                                    "invalid duration for {operation}: {error}"
                                ))
                            })?
                        } else {
                            0
                        };
                        (duration, duration)
                    }
                    _ => unreachable!("validated arena has an Atomic payload"),
                }
            }
            MorphismNodeKind::Instantiate => match payload {
                Some(MorphismPayload::Instantiate { template, .. }) => {
                    let root = arena.templates()[template.index()].root().index();
                    (durations[root], logical_durations[root])
                }
                _ => unreachable!("validated arena has an Instantiate payload"),
            },
            MorphismNodeKind::Serial => {
                let mut duration = 0_u64;
                let mut logical_duration = 0_u64;
                for child in children_by_node(arena, node) {
                    duration = duration
                        .checked_add(durations[child.index()])
                        .ok_or_else(|| {
                            OasmCompileError::new("serial duration overflows u64 cycles")
                        })?;
                    logical_duration = logical_duration
                        .checked_add(logical_durations[child.index()])
                        .ok_or_else(|| {
                            OasmCompileError::new("serial logical duration overflows u64 cycles")
                        })?;
                }
                (duration, logical_duration)
            }
            MorphismNodeKind::Parallel => {
                let duration = children_by_node(arena, node)
                    .iter()
                    .map(|child| durations[child.index()])
                    .max()
                    .unwrap_or(0);
                let logical_duration = children_by_node(arena, node)
                    .iter()
                    .map(|child| logical_durations[child.index()])
                    .max()
                    .unwrap_or(0);
                (duration, logical_duration)
            }
            MorphismNodeKind::DefinitionRef => {
                let definition = match payload {
                    Some(MorphismPayload::DefinitionRef { definition, .. }) => {
                        &arena.definitions()[definition.index()]
                    }
                    _ => "<unknown>",
                };
                return Err(OasmCompileError::new(format!(
                    "unresolved Morphism definition {definition}; specialization is required before RTMQ lowering"
                )));
            }
            MorphismNodeKind::Loop => {
                let Some(MorphismPayload::Loop { count }) = payload else {
                    unreachable!("validated arena has a Loop payload")
                };
                let count = eval_cycles(&evaluated_values, *count)?;
                let body = children_by_node(arena, node)[0];
                let iteration = durations[body.index()]
                    .checked_add(target.loop_timing.iteration_overhead(count))
                    .ok_or_else(|| {
                        OasmCompileError::new("loop iteration duration overflows u64 cycles")
                    })?;
                let duration = target
                    .loop_timing
                    .fixed_overhead_cycles
                    .checked_add(iteration.checked_mul(count).ok_or_else(|| {
                        OasmCompileError::new("loop duration overflows u64 cycles")
                    })?)
                    .ok_or_else(|| OasmCompileError::new("loop duration overflows u64 cycles"))?;
                let logical_duration = logical_durations[body.index()]
                    .checked_mul(count)
                    .ok_or_else(|| {
                        OasmCompileError::new("loop logical duration overflows u64 cycles")
                    })?;
                (duration, logical_duration)
            }
            MorphismNodeKind::SyncPhi => {
                return Err(OasmCompileError::new(format!(
                    "{:?} is not implemented by the 0.3 OASM backend",
                    node.kind()
                )));
            }
        };
        durations[index] = duration;
        logical_durations[index] = logical_duration;
    }

    Ok(TimingAnalysis {
        evaluated_values,
        durations,
        logical_durations,
    })
}
