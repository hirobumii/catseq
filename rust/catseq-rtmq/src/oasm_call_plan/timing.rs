//! Algebraic and scheduled duration analysis for the Morphism DAG.

use catseq_core::morphism_arena::{MorphismNodeKind, MorphismPayload, WaitSemantics};
use catseq_core::native_arenas::NativeArenas;

use super::arena_util::children_by_node;
use super::model::{AtomicLowering, LinkBindings, OasmCompileError, TargetProfile};
use super::value_eval::{
    EvaluatedValue, atomic_bool_argument, eval_cycles, eval_duration_cycles, eval_duration_delta,
    evaluate_link_values,
};

pub(super) struct TimingAnalysis {
    pub(super) evaluated_values: Vec<Result<EvaluatedValue, OasmCompileError>>,
    /// Signed physical cursor displacement for each Morphism node.
    pub(super) durations: Vec<i64>,
    /// Furthest physical timestamp reached relative to each node's start.
    pub(super) frontiers: Vec<i64>,
    /// Furthest logical timestamp reached with hardware overhead excluded.
    pub(super) logical_frontiers: Vec<i64>,
    pub(super) contains_rewind: Vec<bool>,
}

pub(super) fn analyze_timing(
    program: &NativeArenas,
    target: &TargetProfile,
    link_bindings: &LinkBindings,
) -> Result<TimingAnalysis, OasmCompileError> {
    let arena = program.morphisms();
    let evaluated_values = evaluate_link_values(program, link_bindings);
    let mut durations = vec![0_i64; arena.nodes().len()];
    let mut logical_durations = vec![0_i64; arena.nodes().len()];
    let mut frontiers = vec![0_i64; arena.nodes().len()];
    let mut logical_frontiers = vec![0_i64; arena.nodes().len()];
    let mut contains_rewind = vec![false; arena.nodes().len()];
    for (index, node) in arena.nodes().iter().enumerate() {
        let payload = node
            .payload()
            .map(|payload| &arena.payloads()[payload.index()]);
        let (duration, logical_duration, frontier, logical_frontier, rewinds) = match node.kind() {
            MorphismNodeKind::Wait => match payload {
                Some(MorphismPayload::Wait {
                    duration,
                    semantics,
                }) => {
                    let source = &arena.provenance()[node.provenance().index()];
                    let duration = eval_duration_delta(
                        &evaluated_values,
                        *duration,
                        target.duration_quantization,
                    )
                    .map_err(|error| {
                        OasmCompileError::new(format!(
                            "invalid wait at {}:{}:{}: {error}",
                            source.owner(),
                            source.line(),
                            source.column()
                        ))
                    })?;
                    if *semantics == WaitSemantics::PhysicalInterval && duration < 0 {
                        return Err(OasmCompileError::new(format!(
                            "physical interval duration must be non-negative at {}:{}:{}",
                            source.owner(),
                            source.line(),
                            source.column()
                        )));
                    }
                    (
                        duration,
                        duration,
                        duration.max(0),
                        duration.max(0),
                        duration < 0,
                    )
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
                        let duration = i64::try_from(duration).map_err(|_| {
                            OasmCompileError::new(format!(
                                "duration for {operation} exceeds signed Cycle Delta range"
                            ))
                        })?;
                        (duration, duration, duration, duration, false)
                    }
                    _ => unreachable!("validated arena has an Atomic payload"),
                }
            }
            MorphismNodeKind::Instantiate => match payload {
                Some(MorphismPayload::Instantiate { template, .. }) => {
                    let root = arena.templates()[template.index()].root().index();
                    (
                        durations[root],
                        logical_durations[root],
                        frontiers[root],
                        logical_frontiers[root],
                        contains_rewind[root],
                    )
                }
                _ => unreachable!("validated arena has an Instantiate payload"),
            },
            MorphismNodeKind::Serial => {
                let mut duration = 0_i64;
                let mut logical_duration = 0_i64;
                let mut frontier = 0_i64;
                let mut logical_frontier = 0_i64;
                let mut rewinds = false;
                for child in children_by_node(arena, node) {
                    frontier =
                        frontier.max(duration.checked_add(frontiers[child.index()]).ok_or_else(
                            || OasmCompileError::new("serial frontier overflows i64 cycles"),
                        )?);
                    logical_frontier = logical_frontier.max(
                        logical_duration
                            .checked_add(logical_frontiers[child.index()])
                            .ok_or_else(|| {
                                OasmCompileError::new(
                                    "serial logical frontier overflows i64 cycles",
                                )
                            })?,
                    );
                    duration = duration
                        .checked_add(durations[child.index()])
                        .ok_or_else(|| {
                            OasmCompileError::new("serial duration overflows i64 cycles")
                        })?;
                    logical_duration = logical_duration
                        .checked_add(logical_durations[child.index()])
                        .ok_or_else(|| {
                            OasmCompileError::new("serial logical duration overflows i64 cycles")
                        })?;
                    rewinds |= contains_rewind[child.index()];
                }
                (
                    duration,
                    logical_duration,
                    frontier,
                    logical_frontier,
                    rewinds,
                )
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
                let frontier = children_by_node(arena, node)
                    .iter()
                    .map(|child| frontiers[child.index()])
                    .max()
                    .unwrap_or(0);
                let logical_frontier = children_by_node(arena, node)
                    .iter()
                    .map(|child| logical_frontiers[child.index()])
                    .max()
                    .unwrap_or(0);
                let rewinds = children_by_node(arena, node)
                    .iter()
                    .any(|child| contains_rewind[child.index()]);
                (
                    duration,
                    logical_duration,
                    frontier,
                    logical_frontier,
                    rewinds,
                )
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
                if contains_rewind[body.index()] {
                    let count = i64::try_from(count).map_err(|_| {
                        OasmCompileError::new("loop count exceeds signed duration range")
                    })?;
                    let repetitions_before_last = count.saturating_sub(1);
                    let repeated_frontier = |delta: i64, frontier: i64| {
                        let last_start = if delta >= 0 {
                            delta.checked_mul(repetitions_before_last)
                        } else {
                            Some(0)
                        }
                        .ok_or_else(|| {
                            OasmCompileError::new("expanded loop frontier overflows i64 cycles")
                        })?;
                        last_start.checked_add(frontier).ok_or_else(|| {
                            OasmCompileError::new("expanded loop frontier overflows i64 cycles")
                        })
                    };
                    let duration = durations[body.index()].checked_mul(count).ok_or_else(|| {
                        OasmCompileError::new("expanded loop duration overflows i64 cycles")
                    })?;
                    let logical_duration = logical_durations[body.index()]
                        .checked_mul(count)
                        .ok_or_else(|| {
                            OasmCompileError::new(
                                "expanded loop logical duration overflows i64 cycles",
                            )
                        })?;
                    (
                        duration,
                        logical_duration,
                        repeated_frontier(durations[body.index()], frontiers[body.index()])?,
                        repeated_frontier(
                            logical_durations[body.index()],
                            logical_frontiers[body.index()],
                        )?,
                        true,
                    )
                } else {
                    let body_duration = u64::try_from(durations[body.index()]).map_err(|_| {
                        OasmCompileError::new("hardware loop body duration must be non-negative")
                    })?;
                    let iteration = body_duration
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
                        .ok_or_else(|| {
                            OasmCompileError::new("loop duration overflows u64 cycles")
                        })?;
                    let logical_duration = logical_durations[body.index()]
                        .checked_mul(i64::try_from(count).map_err(|_| {
                            OasmCompileError::new("loop count exceeds signed duration range")
                        })?)
                        .ok_or_else(|| {
                            OasmCompileError::new("loop logical duration overflows u64 cycles")
                        })?;
                    let duration = i64::try_from(duration)
                        .map_err(|_| OasmCompileError::new("loop duration exceeds i64 cycles"))?;
                    (
                        duration,
                        logical_duration,
                        duration,
                        logical_duration.max(0),
                        false,
                    )
                }
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
        frontiers[index] = frontier;
        logical_frontiers[index] = logical_frontier;
        contains_rewind[index] = rewinds;
    }

    Ok(TimingAnalysis {
        evaluated_values,
        durations,
        frontiers,
        logical_frontiers,
        contains_rewind,
    })
}
