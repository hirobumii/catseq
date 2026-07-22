//! Morphism traversal and lowering into unscheduled board events.

use std::collections::{BTreeMap, HashMap};

use catseq_core::morphism_arena::{MorphismNodeKind, MorphismPayload};
use catseq_core::native_arenas::NativeArenas;

use super::abi_cost::GLOBAL_SYNC_MARGIN_CYCLES;
use super::arena_util::children_by_node;
use super::atomic_lowering::lower_atomic_events;
use super::epochs::EpochAnalysis;
use super::model::{
    AtomicLowering, CompileEnvironment, DirectEvent, EventOrder, LoopRegion, OasmArgument,
    OasmCompileError, OasmFunction, RwgChannelState, TargetBoardKind, TargetProfile, TtlEvent,
};
use super::timing::TimingAnalysis;
use super::value_eval::eval_cycles;

pub(super) struct LoweredEvents {
    pub(super) ttl_events: Vec<TtlEvent>,
    pub(super) direct_events: Vec<DirectEvent>,
    pub(super) loop_regions: Vec<LoopRegion>,
    pub(super) epoch_origins: BTreeMap<u32, u64>,
}

pub(super) fn lower_events(
    program: &NativeArenas,
    environment: &CompileEnvironment,
    target: &TargetProfile,
    timing: &TimingAnalysis,
    epochs: &EpochAnalysis,
) -> Result<LoweredEvents, OasmCompileError> {
    let arena = program.morphisms();
    let evaluated_values = &timing.evaluated_values;
    let durations = &timing.durations;
    let sync_counts = &epochs.sync_counts;
    let mut ttl_events = Vec::<TtlEvent>::new();
    let mut direct_events = Vec::<DirectEvent>::new();
    let mut rwg_states = HashMap::<String, RwgChannelState>::new();
    let mut rsp_pid_configs = HashMap::<String, serde_json::Value>::new();
    let mut loop_regions = Vec::<LoopRegion>::new();
    enum TraversalTask {
        Visit {
            node_id: usize,
            start: u64,
            epoch: u32,
            channel: Option<usize>,
        },
        FinishLoop {
            start: u64,
            epoch: u32,
            body_duration: u64,
            total_duration: u64,
            count: u64,
            ttl_start: usize,
            direct_start: usize,
        },
    }
    let mut pending = vec![TraversalTask::Visit {
        node_id: arena.root().index(),
        start: 0,
        epoch: 0,
        channel: None,
    }];
    let mut epoch_origins = BTreeMap::from([(0_u32, 0_u64)]);
    let mut next_event_id = 0_u64;
    while let Some(task) = pending.pop() {
        let TraversalTask::Visit {
            node_id,
            start,
            epoch,
            channel,
        } = task
        else {
            let TraversalTask::FinishLoop {
                start,
                epoch,
                body_duration,
                total_duration,
                count,
                ttl_start,
                direct_start,
            } = task
            else {
                unreachable!()
            };
            let boards = ttl_events[ttl_start..]
                .iter()
                .map(|event| event.board.clone())
                .chain(
                    direct_events[direct_start..]
                        .iter()
                        .map(|event| event.board.clone()),
                )
                .collect::<std::collections::BTreeSet<_>>();
            let end = start
                .checked_add(body_duration)
                .ok_or_else(|| OasmCompileError::new("loop timestamp overflows u64"))?;
            let cursor_advance = total_duration.checked_sub(body_duration).ok_or_else(|| {
                OasmCompileError::new("hardware loop duration is shorter than its body")
            })?;
            let marker_group_id = next_event_id;
            next_event_id = next_event_id
                .checked_add(1)
                .ok_or_else(|| OasmCompileError::new("OASM event id overflows u64"))?;
            loop_regions.push(LoopRegion {
                epoch,
                start,
                body_duration,
                count,
                marker_group_id,
            });
            for event in &mut ttl_events[ttl_start..] {
                event.loop_scope = Some(marker_group_id);
            }
            for event in &mut direct_events[direct_start..] {
                event.loop_scope = Some(marker_group_id);
            }
            for board in boards {
                direct_events.push(DirectEvent {
                    epoch,
                    offset_cycles: start,
                    board: board.clone(),
                    function: OasmFunction::LoopBegin,
                    args: vec![OasmArgument::Unsigned(1), OasmArgument::Unsigned(count)],
                    instruction_cost_cycles: 0,
                    order: EventOrder::BOARD,
                    group_id: marker_group_id,
                    preload: false,
                    loop_scope: Some(marker_group_id),
                });
                direct_events.push(DirectEvent {
                    epoch,
                    offset_cycles: end,
                    board,
                    function: OasmFunction::LoopEnd,
                    args: Vec::new(),
                    instruction_cost_cycles: cursor_advance,
                    order: EventOrder::BOARD,
                    group_id: marker_group_id,
                    preload: false,
                    loop_scope: Some(marker_group_id),
                });
            }
            continue;
        };
        let node = &arena.nodes()[node_id];
        let payload = node
            .payload()
            .map(|payload| &arena.payloads()[payload.index()]);
        match node.kind() {
            MorphismNodeKind::Wait => {}
            MorphismNodeKind::Atomic => {
                let group_id = next_event_id;
                next_event_id = next_event_id
                    .checked_add(1)
                    .ok_or_else(|| OasmCompileError::new("OASM event id overflows u64"))?;
                let Some(MorphismPayload::Atomic { operation, .. }) = payload else {
                    unreachable!("validated arena has an Atomic payload")
                };
                let operation = &arena.operations()[operation.index()];
                let schema = target.operations.get(operation).ok_or_else(|| {
                    OasmCompileError::new(format!(
                        "Target Profile has no Atomic Schema for {operation}"
                    ))
                })?;
                let arguments = arena
                    .payload_arguments(payload.expect("Atomic has payload"))
                    .map_err(|error| OasmCompileError::new(error.to_string()))?;
                if schema.lowering == AtomicLowering::GlobalSync {
                    if epoch_origins.insert(epoch + 1, start).is_some() {
                        return Err(OasmCompileError::new(format!(
                            "epoch {epoch} contains more than one global sync boundary"
                        )));
                    }
                    let frontier = direct_events
                        .iter()
                        .filter(|event| event.epoch == epoch)
                        .map(|event| {
                            event
                                .offset_cycles
                                .saturating_add(event.instruction_cost_cycles)
                        })
                        .chain(ttl_events.iter().filter(|event| event.epoch == epoch).map(
                            |event| {
                                event
                                    .offset_cycles
                                    .saturating_add(event.instruction_cost_cycles)
                            },
                        ))
                        .max()
                        .unwrap_or(start);
                    let master_wait = frontier
                        .saturating_sub(start)
                        .saturating_add(GLOBAL_SYNC_MARGIN_CYCLES);
                    for (address, board) in &target.boards {
                        direct_events.push(DirectEvent {
                            epoch,
                            offset_cycles: start,
                            board: address.clone(),
                            function: if board.kind == TargetBoardKind::Main {
                                OasmFunction::TrigSlave
                            } else {
                                OasmFunction::WaitMaster
                            },
                            args: if board.kind == TargetBoardKind::Main {
                                vec![
                                    OasmArgument::Unsigned(master_wait),
                                    OasmArgument::Unsigned(12_345),
                                ]
                            } else {
                                vec![OasmArgument::Unsigned(12_345)]
                            },
                            instruction_cost_cycles: schema.instruction_cost_cycles,
                            order: EventOrder::BOARD,
                            group_id,
                            preload: false,
                            loop_scope: None,
                        });
                    }
                    continue;
                }
                if schema.lowering == AtomicLowering::Opaque {
                    let board = schema.board.as_ref().ok_or_else(|| {
                        OasmCompileError::new(format!(
                            "opaque operation {operation} has no target board"
                        ))
                    })?;
                    let opaque = environment.opaque_calls.get(operation).ok_or_else(|| {
                        OasmCompileError::new(format!(
                            "compile environment has no opaque call binding for {operation}"
                        ))
                    })?;
                    let args = vec![
                        OasmArgument::String(opaque.callable.clone()),
                        OasmArgument::Json(serde_json::Value::Array(opaque.args.clone())),
                        OasmArgument::Json(serde_json::Value::Object(opaque.kwargs.clone())),
                    ];
                    direct_events.push(DirectEvent {
                        epoch,
                        offset_cycles: start,
                        board: board.clone(),
                        function: OasmFunction::UserDefinedFunc,
                        args,
                        instruction_cost_cycles: schema.instruction_cost_cycles,
                        order: EventOrder::BOARD,
                        group_id,
                        preload: false,
                        loop_scope: None,
                    });
                    continue;
                }
                let channel = channel.ok_or_else(|| {
                    OasmCompileError::new(format!(
                        "hardware operation {operation} is not instantiated on a channel"
                    ))
                })?;
                let channel_key = &arena.channels()[channel];
                let binding = environment.channels.get(channel_key).ok_or_else(|| {
                    OasmCompileError::new(format!(
                        "compile environment has no binding for channel {channel_key}"
                    ))
                })?;
                let board = target.boards.get(&binding.board).ok_or_else(|| {
                    OasmCompileError::new(format!(
                        "Target Profile has no board capabilities for {}",
                        binding.board
                    ))
                })?;
                lower_atomic_events(
                    schema,
                    channel_key,
                    binding,
                    board,
                    start,
                    epoch,
                    durations[node_id],
                    arguments,
                    program,
                    evaluated_values,
                    target.clock_hz,
                    target.duration_quantization,
                    group_id,
                    &mut rwg_states,
                    &mut rsp_pid_configs,
                    &mut ttl_events,
                    &mut direct_events,
                )
                .map_err(|error| {
                    let source = &arena.provenance()[node.provenance().index()];
                    OasmCompileError::new(format!(
                        "cannot lower {operation} at {}:{}:{}: {error}",
                        source.owner(),
                        source.line(),
                        source.column()
                    ))
                })?;
            }
            MorphismNodeKind::Instantiate => {
                let Some(MorphismPayload::Instantiate { template, channel }) = payload else {
                    unreachable!("validated arena has an Instantiate payload")
                };
                pending.push(TraversalTask::Visit {
                    node_id: arena.templates()[template.index()].root().index(),
                    start,
                    epoch,
                    channel: Some(channel.index()),
                });
            }
            MorphismNodeKind::Serial => {
                let mut child_start = start;
                let mut child_epoch = epoch;
                let mut children = Vec::new();
                for child in children_by_node(arena, node) {
                    children.push(TraversalTask::Visit {
                        node_id: child.index(),
                        start: child_start,
                        epoch: child_epoch,
                        channel,
                    });
                    child_start = child_start
                        .checked_add(durations[child.index()])
                        .ok_or_else(|| OasmCompileError::new("serial timestamp overflows u64"))?;
                    child_epoch = child_epoch
                        .checked_add(sync_counts[child.index()])
                        .ok_or_else(|| OasmCompileError::new("epoch id overflows u32"))?;
                }
                pending.extend(children.into_iter().rev());
            }
            MorphismNodeKind::Parallel => {
                pending.extend(children_by_node(arena, node).iter().rev().map(|child| {
                    TraversalTask::Visit {
                        node_id: child.index(),
                        start,
                        epoch,
                        channel,
                    }
                }));
            }
            MorphismNodeKind::Loop => {
                let Some(MorphismPayload::Loop { count }) = payload else {
                    unreachable!("validated arena has a Loop payload")
                };
                let count = eval_cycles(evaluated_values, *count)?;
                let body = children_by_node(arena, node)[0];
                let body_duration = durations[body.index()];
                pending.push(TraversalTask::FinishLoop {
                    start,
                    epoch,
                    body_duration,
                    total_duration: durations[node_id],
                    count,
                    ttl_start: ttl_events.len(),
                    direct_start: direct_events.len(),
                });
                pending.push(TraversalTask::Visit {
                    node_id: body.index(),
                    start,
                    epoch,
                    channel,
                });
            }
            MorphismNodeKind::DefinitionRef | MorphismNodeKind::SyncPhi => {
                unreachable!("unsupported nodes were rejected during duration analysis")
            }
        }
    }

    Ok(LoweredEvents {
        ttl_events,
        direct_events,
        loop_regions,
        epoch_origins,
    })
}
