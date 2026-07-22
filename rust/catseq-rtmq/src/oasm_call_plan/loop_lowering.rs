//! Hardware-loop occupancy adjustment before board scheduling.

use std::collections::BTreeMap;

use super::model::{DirectEvent, EventOrder, LoopRegion, OasmCompileError, OasmFunction, TtlEvent};
use super::scheduler::schedule_board_events;

pub(super) fn apply_loop_timing(
    regions: &[LoopRegion],
    ttl_events: &mut [TtlEvent],
    direct_events: &mut [DirectEvent],
    epoch_origins: &mut BTreeMap<u32, u64>,
) -> Result<u64, OasmCompileError> {
    let mut total_delta = 0_u64;
    for region in regions {
        let start = direct_events
            .iter()
            .find(|event| {
                event.group_id == region.marker_group_id
                    && event.function == OasmFunction::LoopBegin
            })
            .map_or(region.start, |event| event.offset_cycles);
        let end = start
            .checked_add(region.body_duration)
            .ok_or_else(|| OasmCompileError::new("loop body end overflows u64"))?;
        let after_body = end
            .checked_add(1)
            .ok_or_else(|| OasmCompileError::new("loop body boundary overflows u64"))?;
        let loop_boards = direct_events
            .iter()
            .filter(|event| {
                event.epoch == region.epoch
                    && event.loop_scope == Some(region.marker_group_id)
                    && event.group_id != region.marker_group_id
            })
            .map(|event| event.board.clone())
            .chain(
                ttl_events
                    .iter()
                    .filter(|event| {
                        event.epoch == region.epoch
                            && event.loop_scope == Some(region.marker_group_id)
                    })
                    .map(|event| event.board.clone()),
            )
            .collect::<std::collections::BTreeSet<_>>();
        for event in direct_events.iter_mut().filter(|event| {
            event.epoch == region.epoch
                && loop_boards.contains(&event.board)
                && event.loop_scope != Some(region.marker_group_id)
                && event.offset_cycles >= start
                && event.offset_cycles <= end
        }) {
            event.offset_cycles = after_body;
        }
        for event in ttl_events.iter_mut().filter(|event| {
            event.epoch == region.epoch
                && loop_boards.contains(&event.board)
                && event.loop_scope != Some(region.marker_group_id)
                && event.offset_cycles >= start
                && event.offset_cycles <= end
        }) {
            event.offset_cycles = after_body;
        }
        // Preload scheduling and call coalescing are board-local operations. Keeping
        // this boundary here prevents equal timestamps on independent boards from
        // being collapsed into one synthetic call while measuring loop occupancy.
        let mut body_events_by_board = BTreeMap::<String, Vec<DirectEvent>>::new();
        for event in direct_events.iter().filter(|event| {
            event.epoch == region.epoch
                && event.loop_scope == Some(region.marker_group_id)
                && event.group_id != region.marker_group_id
        }) {
            body_events_by_board
                .entry(event.board.clone())
                .or_default()
                .push(event.clone());
        }
        let mut ttl_by_offset = BTreeMap::<(String, u64), EventOrder>::new();
        for event in ttl_events.iter().filter(|event| {
            event.epoch == region.epoch && event.loop_scope == Some(region.marker_group_id)
        }) {
            ttl_by_offset
                .entry((event.board.clone(), event.offset_cycles))
                .and_modify(|order| *order = (*order).min(event.order))
                .or_insert(event.order);
        }
        let ttl_direct_events = ttl_by_offset
            .into_iter()
            .map(|((board, offset_cycles), order)| DirectEvent {
                epoch: region.epoch,
                offset_cycles,
                board,
                function: OasmFunction::TtlSet,
                args: Vec::new(),
                instruction_cost_cycles: 1,
                order,
                group_id: order.sequence,
                preload: false,
                loop_scope: Some(region.marker_group_id),
            });
        let scheduled =
            schedule_board_events(body_events_by_board.into_values(), ttl_direct_events)?;
        let mut board_cursors = BTreeMap::<String, u64>::new();
        for event in scheduled {
            let cursor = board_cursors.entry(event.board.clone()).or_insert(start);
            let actual_start = event.offset_cycles.max(*cursor);
            *cursor = actual_start
                .checked_add(event.instruction_cost_cycles)
                .ok_or_else(|| OasmCompileError::new("loop body cursor overflows u64"))?;
        }
        let actual_body_duration = board_cursors
            .values()
            .copied()
            .max()
            .unwrap_or(end)
            .saturating_sub(start)
            .max(region.body_duration);
        let body_delta = actual_body_duration - region.body_duration;
        let loop_delta = body_delta
            .checked_mul(region.count)
            .ok_or_else(|| OasmCompileError::new("loop lowering delta overflows u64"))?;
        if loop_delta == 0 {
            continue;
        }
        let marker_extra = loop_delta.saturating_sub(body_delta);
        for event in direct_events.iter_mut() {
            if event.group_id == region.marker_group_id && event.function == OasmFunction::LoopEnd {
                event.instruction_cost_cycles = event
                    .instruction_cost_cycles
                    .checked_add(marker_extra)
                    .ok_or_else(|| OasmCompileError::new("loop marker cost overflows u64"))?;
            } else if event.epoch > region.epoch
                || (event.epoch == region.epoch && event.offset_cycles > end)
            {
                event.offset_cycles = event
                    .offset_cycles
                    .checked_add(loop_delta)
                    .ok_or_else(|| OasmCompileError::new("post-loop timestamp overflows u64"))?;
            }
        }
        for event in ttl_events.iter_mut().filter(|event| {
            event.epoch > region.epoch || (event.epoch == region.epoch && event.offset_cycles > end)
        }) {
            event.offset_cycles = event
                .offset_cycles
                .checked_add(loop_delta)
                .ok_or_else(|| OasmCompileError::new("post-loop TTL timestamp overflows u64"))?;
        }
        for origin in epoch_origins.values_mut().filter(|origin| **origin > end) {
            *origin = origin
                .checked_add(loop_delta)
                .ok_or_else(|| OasmCompileError::new("post-loop epoch origin overflows u64"))?;
        }
        total_delta = total_delta
            .checked_add(loop_delta)
            .ok_or_else(|| OasmCompileError::new("program loop delta overflows u64"))?;
    }
    Ok(total_delta)
}
