//! Final cost accounting, board scheduling, and call-plan construction.

use std::collections::BTreeMap;

use catseq_core::native_arenas::NativeArenas;

use super::abi_cost::{GLOBAL_SYNC_MARGIN_CYCLES, fixed_oasm_call_cost, oasm_call_cost};
use super::epochs::EpochAnalysis;
use super::event_lowering::LoweredEvents;
use super::loop_lowering::apply_loop_timing;
use super::model::{
    BoardEpochInput, DirectEvent, OasmArgument, OasmCallPlan, OasmCompileError, OasmEpochPlan,
    OasmFunction, TargetProfile, TtlEvent,
};
use super::scheduler::compile_board;
use super::timing::TimingAnalysis;

pub(super) fn build_call_plan(
    program: &NativeArenas,
    target: &TargetProfile,
    timing: &TimingAnalysis,
    epoch_analysis: &EpochAnalysis,
    lowered: LoweredEvents,
) -> Result<OasmCallPlan, OasmCompileError> {
    let arena = program.morphisms();
    let durations = &timing.durations;
    let logical_durations = &timing.logical_durations;
    let sync_counts = &epoch_analysis.sync_counts;
    let LoweredEvents {
        mut ttl_events,
        mut direct_events,
        loop_regions,
        mut epoch_origins,
    } = lowered;
    for event in &mut direct_events {
        event.instruction_cost_cycles = event.instruction_cost_cycles.max(oasm_call_cost(event)?);
    }
    let loop_delta = apply_loop_timing(
        &loop_regions,
        &mut ttl_events,
        &mut direct_events,
        &mut epoch_origins,
    )?;
    let program_duration = durations[arena.root().index()]
        .checked_add(loop_delta)
        .ok_or_else(|| OasmCompileError::new("program duration overflows u64"))?;

    let mut board_ttl_events = BTreeMap::<(u32, String), Vec<TtlEvent>>::new();
    for event in ttl_events {
        board_ttl_events
            .entry((event.epoch, event.board.clone()))
            .or_default()
            .push(event);
    }
    let mut board_direct_events = BTreeMap::<(u32, String), Vec<DirectEvent>>::new();
    for event in direct_events {
        board_direct_events
            .entry((event.epoch, event.board.clone()))
            .or_default()
            .push(event);
    }
    let program_addresses = board_ttl_events
        .keys()
        .chain(board_direct_events.keys())
        .map(|(_, address)| address.clone())
        .collect::<std::collections::BTreeSet<_>>();
    let mut epochs = Vec::new();
    let mut epoch_initial_cursors = BTreeMap::<String, u64>::new();
    for id in 0..=sync_counts[arena.root().index()] {
        let origin_cycles = *epoch_origins.get(&id).ok_or_else(|| {
            OasmCompileError::new(format!("epoch {id} has no global sync origin"))
        })?;
        let end_cycles = epoch_origins
            .get(&(id + 1))
            .copied()
            .unwrap_or(program_duration);
        let duration_cycles = end_cycles
            .checked_sub(origin_cycles)
            .ok_or_else(|| OasmCompileError::new("epoch end precedes its origin"))?;
        let mut boards = program_addresses
            .iter()
            .map(|address| {
                let board = target.boards.get(address).ok_or_else(|| {
                    OasmCompileError::new(format!(
                        "Target Profile has no board capabilities for {address}"
                    ))
                })?;
                compile_board(BoardEpochInput {
                    epoch: id,
                    origin_cycles,
                    address: address.clone(),
                    board_kind: board.kind,
                    duration_cycles,
                    initial_cursor: epoch_initial_cursors.get(address).copied().unwrap_or(0),
                    ttl_events: board_ttl_events
                        .remove(&(id, address.clone()))
                        .unwrap_or_default(),
                    direct_events: board_direct_events
                        .remove(&(id, address.clone()))
                        .unwrap_or_default(),
                })
            })
            .collect::<Result<Vec<_>, _>>()?;
        let sync_frontier = boards
            .iter()
            .flat_map(|board| board.calls.iter())
            .filter(|call| {
                matches!(
                    call.function,
                    OasmFunction::WaitMaster | OasmFunction::TrigSlave
                )
            })
            .map(|call| {
                call.offset_cycles
                    + if call.function == OasmFunction::WaitMaster {
                        fixed_oasm_call_cost(call.function)
                            .expect("WaitMaster has a fixed ABI cost")
                    } else {
                        0
                    }
            })
            .max();
        if let Some(sync_frontier) = sync_frontier {
            for board in &mut boards {
                for call in &mut board.calls {
                    if call.function == OasmFunction::TrigSlave {
                        let master_wait = sync_frontier
                            .saturating_sub(call.offset_cycles)
                            .saturating_add(GLOBAL_SYNC_MARGIN_CYCLES);
                        if let Some(argument) = call.args.first_mut() {
                            *argument = OasmArgument::Unsigned(master_wait);
                        }
                    }
                }
            }
        }
        epoch_initial_cursors.clear();
        for board in &boards {
            let carry = board
                .calls
                .iter()
                .rev()
                .find_map(|call| match call.function {
                    OasmFunction::WaitMaster | OasmFunction::TrigSlave => {
                        fixed_oasm_call_cost(call.function)
                    }
                    _ => None,
                });
            if let Some(carry) = carry {
                epoch_initial_cursors.insert(board.address.clone(), carry);
            }
        }
        epochs.push(OasmEpochPlan {
            id,
            origin_cycles,
            boards,
        });
    }
    Ok(OasmCallPlan {
        schema_version: 1,
        epochs,
        logical_duration_cycles: logical_durations[arena.root().index()],
    })
}
