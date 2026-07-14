//! Board-local instruction scheduling after logical Morphism timing is known.

use std::collections::BTreeMap;

use super::abi_cost::oasm_call_cost;
use super::{
    BoardEpochInput, DirectEvent, EventOrder, LoopRegion, OasmArgument, OasmBoardPlan, OasmCall,
    OasmCompileError, OasmFunction, TtlEvent,
};

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
        let mut scheduled = Vec::new();
        for mut body_events in body_events_by_board.into_values() {
            let fused_handoffs = eliminate_superseded_preloads(&mut body_events);
            schedule_preloads(&mut body_events)?;
            remove_fused_handoff_plays(&mut body_events, &fused_handoffs);
            scheduled.extend(coalesce_direct_events(body_events)?);
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
        scheduled.extend(
            ttl_by_offset
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
                }),
        );
        scheduled.sort_by_key(|event| {
            (
                event.offset_cycles,
                oasm_function_priority(event.function),
                event.order,
            )
        });
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

pub(super) fn compile_board(input: BoardEpochInput) -> Result<OasmBoardPlan, OasmCompileError> {
    let BoardEpochInput {
        epoch,
        origin_cycles,
        address,
        board_kind,
        duration_cycles,
        initial_cursor,
        ttl_events: mut events,
        mut direct_events,
    } = input;
    for event in &mut events {
        if event.epoch != epoch {
            return Err(OasmCompileError::new(
                "TTL event is assigned to the wrong epoch",
            ));
        }
        event.offset_cycles = event
            .offset_cycles
            .checked_sub(origin_cycles)
            .ok_or_else(|| OasmCompileError::new("TTL event precedes its epoch origin"))?;
    }
    for event in &mut direct_events {
        if event.epoch != epoch {
            return Err(OasmCompileError::new(
                "direct event is assigned to the wrong epoch",
            ));
        }
        event.offset_cycles = event
            .offset_cycles
            .checked_sub(origin_cycles)
            .ok_or_else(|| OasmCompileError::new("direct event precedes its epoch origin"))?;
    }
    events.sort_by_key(|event| (event.offset_cycles, event.local_id));
    for event in &mut direct_events {
        event.instruction_cost_cycles = event.instruction_cost_cycles.max(oasm_call_cost(event)?);
    }
    let fused_handoffs = eliminate_superseded_preloads(&mut direct_events);
    schedule_preloads(&mut direct_events)?;
    remove_fused_handoff_plays(&mut direct_events, &fused_handoffs);
    let mut scheduled = coalesce_direct_events(direct_events)?;
    let mut index = 0;
    while index < events.len() {
        let offset = events[index].offset_cycles;
        let mut mask = 0_u64;
        let mut state = 0_u64;
        let mut instruction_cost_cycles = 0_u64;
        while index < events.len() && events[index].offset_cycles == offset {
            let event = &events[index];
            mask |= 1_u64 << event.local_id;
            if event.high {
                state |= 1_u64 << event.local_id;
            }
            instruction_cost_cycles = instruction_cost_cycles.max(event.instruction_cost_cycles);
            index += 1;
        }
        scheduled.push(DirectEvent {
            epoch,
            offset_cycles: offset,
            board: address.clone(),
            function: OasmFunction::TtlSet,
            args: vec![
                OasmArgument::Unsigned(mask),
                OasmArgument::Unsigned(state),
                OasmArgument::String(board_kind.oasm_argument().to_owned()),
            ],
            instruction_cost_cycles,
            order: events[index - 1].order,
            group_id: events[index - 1].order.sequence,
            preload: false,
            loop_scope: events[index - 1].loop_scope,
        });
    }
    for event in &mut scheduled {
        event.instruction_cost_cycles = event.instruction_cost_cycles.max(oasm_call_cost(event)?);
    }
    scheduled.sort_by_key(|event| {
        (
            event.offset_cycles,
            oasm_function_priority(event.function),
            event.order,
        )
    });
    let mut calls = Vec::with_capacity(scheduled.len());
    let mut cursor = initial_cursor;
    for event in scheduled {
        if event.offset_cycles > cursor {
            calls.push(OasmCall {
                offset_cycles: cursor,
                function: OasmFunction::Wait,
                args: vec![OasmArgument::Unsigned(event.offset_cycles - cursor)],
            });
        }
        let actual_start = event.offset_cycles.max(cursor);
        calls.push(OasmCall {
            offset_cycles: actual_start,
            function: event.function,
            args: event.args,
        });
        cursor = actual_start
            .checked_add(event.instruction_cost_cycles)
            .ok_or_else(|| OasmCompileError::new("OASM cursor overflows u64"))?;
    }
    if duration_cycles > cursor {
        calls.push(OasmCall {
            offset_cycles: cursor,
            function: OasmFunction::Wait,
            args: vec![OasmArgument::Unsigned(duration_cycles - cursor)],
        });
    }
    Ok(OasmBoardPlan { address, calls })
}

fn coalesce_direct_events(
    mut events: Vec<DirectEvent>,
) -> Result<Vec<DirectEvent>, OasmCompileError> {
    events.sort_by_key(|event| (event.offset_cycles, coalesce_priority(event.function)));
    let mut coalesced = Vec::<DirectEvent>::with_capacity(events.len());
    for event in events {
        let mergeable = matches!(
            event.function,
            OasmFunction::TtlConfig | OasmFunction::RwgInit | OasmFunction::RwgPlay
        );
        let Some(previous) = coalesced.last_mut().filter(|previous| {
            mergeable
                && previous.offset_cycles == event.offset_cycles
                && previous.function == event.function
        }) else {
            coalesced.push(event);
            continue;
        };
        previous.instruction_cost_cycles = previous
            .instruction_cost_cycles
            .max(event.instruction_cost_cycles);
        previous.order = previous.order.min(event.order);
        match event.function {
            OasmFunction::RwgInit => {}
            OasmFunction::TtlConfig | OasmFunction::RwgPlay => {
                if previous.args.len() != 2 || event.args.len() != 2 {
                    return Err(OasmCompileError::new(
                        "mask-coalesced OASM call does not have two arguments",
                    ));
                }
                for index in 0..2 {
                    let left = match previous.args[index] {
                        OasmArgument::Unsigned(value) => value,
                        _ => {
                            return Err(OasmCompileError::new(
                                "mask-coalesced OASM argument is not unsigned",
                            ));
                        }
                    };
                    let right = match event.args[index] {
                        OasmArgument::Unsigned(value) => value,
                        _ => {
                            return Err(OasmCompileError::new(
                                "mask-coalesced OASM argument is not unsigned",
                            ));
                        }
                    };
                    previous.args[index] = OasmArgument::Unsigned(left | right);
                }
            }
            _ => unreachable!("only mergeable functions reach this branch"),
        }
    }
    Ok(coalesced)
}

const fn coalesce_priority(function: OasmFunction) -> u8 {
    match function {
        OasmFunction::RwgInit => 0,
        OasmFunction::TtlConfig => 1,
        OasmFunction::RwgPlay => 2,
        _ => 3,
    }
}

fn schedule_preloads(events: &mut [DirectEvent]) -> Result<(), OasmCompileError> {
    let mut groups = BTreeMap::<(u64, u64, EventOrder), Vec<usize>>::new();
    for (index, event) in events.iter().enumerate() {
        if event.preload {
            groups
                .entry((event.group_id, event.offset_cycles, event.order))
                .or_default()
                .push(index);
        }
    }
    let mut pairs = groups
        .into_iter()
        .filter_map(|((group_id, deadline, order), indices)| {
            events
                .iter()
                .any(|event| {
                    event.group_id == group_id
                        && event.offset_cycles == deadline
                        && event.function == OasmFunction::RwgPlay
                })
                .then_some((deadline, order, group_id, indices))
        })
        .collect::<Vec<_>>();
    pairs.sort_by_key(|(deadline, order, ..)| (*deadline, *order));

    let mut next_load_available = u64::MAX;
    for (deadline, _order, group_id, indices) in pairs.into_iter().rev() {
        let cost = indices.iter().try_fold(0_u64, |total, index| {
            total
                .checked_add(events[*index].instruction_cost_cycles)
                .ok_or_else(|| OasmCompileError::new("RWG preload cost overflows u64"))
        })?;
        let latest_finish = deadline.min(next_load_available);
        let proposed_start = latest_finish.saturating_sub(cost);
        let proposed_end = proposed_start.saturating_add(cost);
        let conflict = events
            .iter()
            .filter(|event| {
                !(event.preload
                    || (event.group_id == group_id
                        && event.offset_cycles == deadline
                        && event.function == OasmFunction::RwgPlay))
            })
            .filter_map(|event| {
                let event_end = event
                    .offset_cycles
                    .saturating_add(event.instruction_cost_cycles);
                (proposed_start < event_end && proposed_end > event.offset_cycles)
                    .then_some(event.offset_cycles)
            })
            .min();
        let finish = conflict.unwrap_or(latest_finish);
        let start = finish.saturating_sub(cost);
        for index in indices {
            events[index].offset_cycles = start;
        }
        next_load_available = start;
    }
    Ok(())
}

type PreloadKey = (u64, u8, u8);

fn eliminate_superseded_preloads(
    events: &mut Vec<DirectEvent>,
) -> std::collections::BTreeSet<PreloadKey> {
    let preload_groups = events.iter().filter(|event| event.preload).fold(
        BTreeMap::<(u64, u8, u8), std::collections::BTreeSet<u64>>::new(),
        |mut groups, event| {
            groups
                .entry((
                    event.offset_cycles,
                    event.order.channel_kind,
                    event.order.local_id,
                ))
                .or_default()
                .insert(event.group_id);
            groups
        },
    );
    let latest_groups = events.iter().filter(|event| event.preload).fold(
        BTreeMap::<(u64, u8, u8), u64>::new(),
        |mut latest, event| {
            latest
                .entry((
                    event.offset_cycles,
                    event.order.channel_kind,
                    event.order.local_id,
                ))
                .and_modify(|group| *group = (*group).max(event.group_id))
                .or_insert(event.group_id);
            latest
        },
    );
    let fused_handoffs = preload_groups
        .iter()
        .filter_map(|(key, groups)| (groups.len() > 1).then_some(*key))
        .collect::<std::collections::BTreeSet<_>>();
    events.retain(|event| {
        let key = (
            event.offset_cycles,
            event.order.channel_kind,
            event.order.local_id,
        );
        !event.preload
            || latest_groups
                .get(&key)
                .is_none_or(|group| *group == event.group_id)
    });
    fused_handoffs
}

fn remove_fused_handoff_plays(
    events: &mut Vec<DirectEvent>,
    fused_handoffs: &std::collections::BTreeSet<PreloadKey>,
) {
    events.retain(|event| {
        event.function != OasmFunction::RwgPlay
            || !fused_handoffs.contains(&(
                event.offset_cycles,
                event.order.channel_kind,
                event.order.local_id,
            ))
    });
}

fn oasm_function_priority(function: OasmFunction) -> u8 {
    match function {
        OasmFunction::LoopBegin => 0,
        OasmFunction::RwgInit => 1,
        OasmFunction::WaitMaster | OasmFunction::TrigSlave => 3,
        OasmFunction::LoopEnd => 4,
        _ => 2,
    }
}
