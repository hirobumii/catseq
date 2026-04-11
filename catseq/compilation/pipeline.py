"""
Compiler pipeline internals.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from ..lanes import merge_board_lanes
from ..types.common import (
    AtomicMorphism,
    BlackBoxAtomicMorphism,
    Channel,
    OperationType,
    TIMING_CRITICAL_OPERATIONS,
)
from ..types.rwg import RWGActive
from ..types.timing import LogicalTimestamp
from .execution import OASM_AVAILABLE
from .timing_analysis import analyze_operation_cost
from .types import OASMAddress, OASMCall, OASMFunction


WAIT_TIME_PLACEHOLDER = -999999


@dataclass
class LogicalEvent:
    timestamp_cycles: int
    operation: AtomicMorphism
    oasm_calls: List[OASMCall] = field(default_factory=list)
    cost_cycles: int = 0
    is_critical: bool = True
    logical_timestamp: LogicalTimestamp = field(default=None)

    def __post_init__(self):
        if self.logical_timestamp is None:
            self.logical_timestamp = LogicalTimestamp.from_cycles(0, self.timestamp_cycles)

    @property
    def effective_timestamp_cycles(self) -> int:
        return self.logical_timestamp.time_offset_cycles

    @property
    def epoch(self) -> int:
        return self.logical_timestamp.epoch

    def is_same_epoch(self, other: "LogicalEvent") -> bool:
        return self.logical_timestamp.epoch == other.logical_timestamp.epoch


@dataclass(frozen=True)
class PipelinePair:
    load_event: LogicalEvent
    play_event: LogicalEvent

    @property
    def channel(self) -> Channel:
        return self.load_event.operation.channel

    @property
    def load_cost_cycles(self) -> int:
        return self.load_event.cost_cycles

    @property
    def play_start_time(self) -> int:
        return self.play_event.timestamp_cycles


def detect_epoch_boundaries(events: List[LogicalEvent]) -> List[LogicalEvent]:
    if not events:
        return events
    events_by_timestamp: Dict[int, List[LogicalEvent]] = {}
    for event in events:
        events_by_timestamp.setdefault(event.timestamp_cycles, []).append(event)

    processed_events = []
    current_epoch = 0
    for timestamp in sorted(events_by_timestamp.keys()):
        timestamp_events = events_by_timestamp[timestamp]
        has_sync_master = any(
            e.operation.operation_type == OperationType.SYNC_MASTER for e in timestamp_events
        )
        has_sync_slave = any(
            e.operation.operation_type == OperationType.SYNC_SLAVE for e in timestamp_events
        )
        for event in timestamp_events:
            event.logical_timestamp = LogicalTimestamp.from_cycles(current_epoch, timestamp)
            processed_events.append(event)
        if has_sync_master and has_sync_slave:
            current_epoch += 1
    return processed_events


def extract_and_translate(morphism, verbose: bool = False) -> Dict[OASMAddress, List[LogicalEvent]]:
    if verbose:
        print("Compiler: extracting events and translating to OASM calls...")

    events_by_board: Dict[OASMAddress, List[LogicalEvent]] = {}
    for board, board_lanes in morphism.lanes_by_board().items():
        try:
            adr = OASMAddress(board.id.lower())
        except ValueError:
            print(f"Warning: Board ID '{board.id}' not found in OASMAddress enum. Defaulting to RWG0.")
            adr = OASMAddress.RWG0
        events_by_board.setdefault(adr, [])
        physical_lane = merge_board_lanes(board, board_lanes)
        for pop in physical_lane.operations:
            if pop.operation.operation_type == OperationType.IDENTITY:
                continue
            events_by_board[adr].append(
                LogicalEvent(
                    timestamp_cycles=pop.timestamp_cycles,
                    operation=pop.operation,
                    is_critical=pop.operation.operation_type in TIMING_CRITICAL_OPERATIONS,
                )
            )

    for adr, events in events_by_board.items():
        events.sort(key=lambda e: e.timestamp_cycles)
        _translate_board_events(adr, events)

    return events_by_board


def _translate_board_events(adr: OASMAddress, events: List[LogicalEvent]) -> None:
    events_by_ts: Dict[int, List[LogicalEvent]] = {}
    for event in events:
        events_by_ts.setdefault(event.timestamp_cycles, []).append(event)

    for ts, ts_events in events_by_ts.items():
        ops_by_type: Dict[OperationType, List[AtomicMorphism]] = {}
        for event in ts_events:
            ops_by_type.setdefault(event.operation.operation_type, []).append(event.operation)

        for event in ts_events:
            op = event.operation
            match op.operation_type:
                case OperationType.RWG_INIT:
                    pass
                case OperationType.RWG_SET_CARRIER:
                    event.oasm_calls.append(
                        OASMCall(
                            adr=adr,
                            dsl_func=OASMFunction.RWG_SET_CARRIER,
                            args=(op.channel.local_id, op.end_state.carrier_freq),
                        )
                    )
                case OperationType.RWG_RF_SWITCH:
                    ch_mask = 1 << op.channel.local_id
                    state_mask = 0 if op.end_state.rf_on else ch_mask
                    event.oasm_calls.append(
                        OASMCall(
                            adr=adr,
                            dsl_func=OASMFunction.RWG_RF_SWITCH,
                            args=(ch_mask, state_mask),
                        )
                    )
                case OperationType.SYNC_MASTER:
                    event.oasm_calls.append(
                        OASMCall(
                            adr=adr,
                            dsl_func=OASMFunction.TRIG_SLAVE,
                            args=(WAIT_TIME_PLACEHOLDER, 12345),
                        )
                    )
                case OperationType.SYNC_SLAVE:
                    pass
                case OperationType.RWG_LOAD_COEFFS:
                    if isinstance(op.end_state, RWGActive) and op.end_state.pending_waveforms:
                        for waveform_params in op.end_state.pending_waveforms:
                            event.oasm_calls.append(
                                OASMCall(
                                    adr=adr,
                                    dsl_func=OASMFunction.RWG_LOAD_WAVEFORM,
                                    args=(waveform_params,),
                                )
                            )
                case _:
                    pass

        if OperationType.RWG_INIT in ops_by_type:
            for event in ts_events:
                if event.operation.operation_type == OperationType.RWG_INIT:
                    board_init_added = any(
                        call.dsl_func == OASMFunction.RWG_INIT
                        for other_event in ts_events
                        for call in other_event.oasm_calls
                    )
                    if not board_init_added:
                        event.oasm_calls.insert(
                            0, OASMCall(adr=adr, dsl_func=OASMFunction.RWG_INIT, args=())
                        )
                    break

        if OperationType.SYNC_SLAVE in ops_by_type:
            for event in ts_events:
                if event.operation.operation_type == OperationType.SYNC_SLAVE:
                    event.oasm_calls.append(
                        OASMCall(adr=adr, dsl_func=OASMFunction.WAIT_MASTER, args=(12345,))
                    )
                    break

        if OperationType.TTL_INIT in ops_by_type:
            mask, dir_value = 0, 0
            for op in ops_by_type[OperationType.TTL_INIT]:
                mask |= 1 << op.channel.local_id
                if op.end_state.value == 1:
                    dir_value |= 1 << op.channel.local_id
            for event in ts_events:
                if event.operation.operation_type == OperationType.TTL_INIT:
                    event.oasm_calls.append(
                        OASMCall(adr=adr, dsl_func=OASMFunction.TTL_CONFIG, args=(mask, dir_value))
                    )
                    break

        if OperationType.TTL_ON in ops_by_type or OperationType.TTL_OFF in ops_by_type:
            mask, state_value = 0, 0
            for op in ops_by_type.get(OperationType.TTL_ON, []):
                mask |= 1 << op.channel.local_id
                state_value |= 1 << op.channel.local_id
            for op in ops_by_type.get(OperationType.TTL_OFF, []):
                mask |= 1 << op.channel.local_id
            if mask > 0:
                board_type = "main" if adr == OASMAddress.MAIN else "rwg"
                for event in ts_events:
                    if event.operation.operation_type in [OperationType.TTL_ON, OperationType.TTL_OFF]:
                        event.oasm_calls.append(
                            OASMCall(
                                adr=adr,
                                dsl_func=OASMFunction.TTL_SET,
                                args=(mask, state_value, board_type),
                            )
                        )
                        break

        if OperationType.RWG_UPDATE_PARAMS in ops_by_type:
            pud_mask, iou_mask = 0, 0
            for op in ops_by_type[OperationType.RWG_UPDATE_PARAMS]:
                ch_local_id = op.channel.local_id
                pud_mask |= 1 << ch_local_id
                iou_mask |= 1 << ch_local_id
            for event in ts_events:
                if event.operation.operation_type == OperationType.RWG_UPDATE_PARAMS:
                    event.oasm_calls.append(
                        OASMCall(adr=adr, dsl_func=OASMFunction.RWG_PLAY, args=(pud_mask, iou_mask))
                    )
                    break

        opaque_events = [e for e in ts_events if isinstance(e.operation, BlackBoxAtomicMorphism)]
        if opaque_events:
            first_op = opaque_events[0].operation
            func_id = id(first_op.user_func)
            for other_event in opaque_events[1:]:
                if id(other_event.operation.user_func) != func_id:
                    raise ValueError(
                        f"Cannot execute two different black-box functions on the same board at the same time. "
                        f"Found {first_op.user_func.__name__} and {other_event.operation.user_func.__name__} at timestamp {ts}."
                    )
            opaque_events[0].oasm_calls.append(
                OASMCall(
                    adr=adr,
                    dsl_func=OASMFunction.USER_DEFINED_FUNC,
                    args=(first_op.user_func, first_op.user_args, first_op.user_kwargs),
                )
            )


def analyze_costs_and_epochs(
    events_by_board: Dict[OASMAddress, List[LogicalEvent]],
    assembler_seq=None,
    verbose: bool = False,
) -> None:
    if verbose:
        print("Compiler: analyzing costs and epoch boundaries...")
    all_events = [event for events in events_by_board.values() for event in events]
    detect_epoch_boundaries(all_events)

    for events in events_by_board.values():
        for event in events:
            if isinstance(event.operation, BlackBoxAtomicMorphism):
                event.cost_cycles = event.operation.duration_cycles

    if assembler_seq is None:
        if OASM_AVAILABLE and verbose:
            print("    Warning: No assembler provided. Standard cost analysis will be skipped.")
        return

    for adr, events in events_by_board.items():
        for event in events:
            if isinstance(event.operation, BlackBoxAtomicMorphism):
                continue
            event.cost_cycles = (
                analyze_operation_cost(event, adr, assembler_seq, verbose=verbose)
                if event.oasm_calls
                else 0
            )


def schedule_and_optimize(
    events_by_board: Dict[OASMAddress, List[LogicalEvent]],
    verbose: bool = False,
) -> None:
    if verbose:
        print("Compiler: scheduling with pipelining optimization...")
    for adr, events in events_by_board.items():
        pipeline_pairs = identify_pipeline_pairs(events, verbose=verbose)
        if pipeline_pairs:
            events_by_board[adr] = calculate_optimal_schedule(events, pipeline_pairs, verbose=verbose)


def identify_load_play_pairs(
    load_events: List[LogicalEvent], play_events: List[LogicalEvent]
) -> List[Dict]:
    pairs = []
    for load_event in load_events:
        load_channel = load_event.operation.channel
        load_time = load_event.timestamp_cycles
        corresponding_play = None
        min_time_diff = float("inf")
        for play_event in play_events:
            if play_event.operation.channel == load_channel and play_event.timestamp_cycles >= load_time:
                time_diff = play_event.timestamp_cycles - load_time
                if time_diff < min_time_diff:
                    min_time_diff = time_diff
                    corresponding_play = play_event
        if corresponding_play:
            pairs.append(
                {
                    "load_event": load_event,
                    "play_event": corresponding_play,
                    "channel": load_channel,
                }
            )
    return pairs


def validate_constraints(
    events_by_board: Dict[OASMAddress, List[LogicalEvent]], verbose: bool = False
) -> None:
    for adr, events in events_by_board.items():
        validate_serial_load_constraints(adr, events, verbose=verbose)
        validate_load_deadlines(adr, events, verbose=verbose)
        validate_timing_consistency(adr, events, verbose=verbose)
        check_cross_epoch_violations_single_board(adr, events, verbose=verbose)
        validate_black_box_exclusivity(adr, events, verbose=verbose)


def validate_black_box_exclusivity(adr, events: List[LogicalEvent], verbose: bool = False):
    opaque_events = [e for e in events if isinstance(e.operation, BlackBoxAtomicMorphism)]
    other_events = [e for e in events if not isinstance(e.operation, BlackBoxAtomicMorphism)]
    if not opaque_events:
        return
    black_box_windows = {}
    for event in opaque_events:
        func_id = id(event.operation.user_func)
        if func_id not in black_box_windows:
            black_box_windows[func_id] = (event.timestamp_cycles, event.timestamp_cycles + event.cost_cycles)
    for start_a, end_a in black_box_windows.values():
        for event_b in other_events:
            start_b = event_b.timestamp_cycles
            end_b = start_b + event_b.cost_cycles
            if (start_a < end_b) and (end_a > start_b):
                raise ValueError(
                    f"Constraint violation on board {adr.value}: Operation {event_b.operation} at t={start_b}c "
                    f"conflicts with a black-box operation running in window [{start_a}c, {end_a}c]. "
                    f"Black-box operations require exclusive access to the board."
                )


def validate_serial_load_constraints(adr, events: List[LogicalEvent], verbose: bool = False):
    load_events = [e for e in events if e.operation.operation_type == OperationType.RWG_LOAD_COEFFS]
    if len(load_events) <= 1:
        return
    sorted_loads = sorted(load_events, key=lambda x: x.timestamp_cycles)
    for i in range(len(sorted_loads) - 1):
        current_load = sorted_loads[i]
        next_load = sorted_loads[i + 1]
        current_end = current_load.timestamp_cycles + (current_load.cost_cycles or 0)
        next_start = next_load.timestamp_cycles
        if next_start < current_end:
            raise ValueError(
                f"Serial constraint violation on board {adr.value}: "
                f"LOAD operations overlap - load1 ends at {current_end}c, load2 starts at {next_start}c"
            )


def validate_load_deadlines(adr, events: List[LogicalEvent], verbose: bool = False):
    load_events = [e for e in events if e.operation.operation_type == OperationType.RWG_LOAD_COEFFS]
    play_events = [e for e in events if e.operation.operation_type == OperationType.RWG_UPDATE_PARAMS]
    if not load_events or not play_events:
        return
    for pair in identify_load_play_pairs(load_events, play_events):
        load_event = pair["load_event"]
        play_event = pair["play_event"]
        load_end = load_event.timestamp_cycles + (load_event.cost_cycles or 0)
        play_start = play_event.timestamp_cycles
        if load_end > play_start:
            raise ValueError(
                f"Deadline violation on board {adr.value}: "
                f"LOAD operation ends at {load_end}c but PLAY starts at {play_start}c"
            )


def validate_timing_consistency(adr, events: List[LogicalEvent], verbose: bool = False):
    for event in events:
        if event.timestamp_cycles < 0:
            raise ValueError(
                f"Timing consistency violation on board {adr.value}: "
                f"Event has negative timestamp: {event.timestamp_cycles}c"
            )
    sorted_events = sorted(events, key=lambda x: x.timestamp_cycles)
    prev_time = 0
    for event in sorted_events:
        if event.timestamp_cycles < prev_time:
            raise ValueError(
                f"Timing consistency violation on board {adr.value}: "
                "Events are not properly ordered in time"
            )
        prev_time = event.timestamp_cycles


def check_cross_epoch_violations_single_board(
    adr, events: List[LogicalEvent], verbose: bool = False
):
    events_by_epoch = {}
    for event in events:
        epoch = getattr(event.logical_timestamp, "epoch", 0) if hasattr(event, "logical_timestamp") else 0
        events_by_epoch.setdefault(epoch, []).append(event)
    if len(events_by_epoch) <= 1:
        return
    epochs = sorted(events_by_epoch.keys())
    for i in range(len(epochs) - 1):
        next_epoch = epochs[i + 1]
        next_events = events_by_epoch[next_epoch]
        for next_event in next_events:
            if (
                next_event.operation.operation_type == OperationType.RWG_LOAD_COEFFS
                and hasattr(next_event, "logical_timestamp")
                and next_event.logical_timestamp.time_offset_cycles < 100
            ):
                raise ValueError(
                    f"Cross-epoch violation on board {adr.value}: "
                    f"LOAD operation at epoch {next_epoch} appears to be pipelined from epoch {epochs[i]}"
                )


def identify_pipeline_pairs(events: List[LogicalEvent], verbose: bool = False) -> List[PipelinePair]:
    pairs = []
    events_by_channel: Dict[Channel, List[LogicalEvent]] = {}
    for event in events:
        channel = event.operation.channel
        if channel is None:
            continue
        events_by_channel.setdefault(channel, []).append(event)

    for channel, channel_events in events_by_channel.items():
        channel_events.sort(key=lambda e: e.timestamp_cycles)
        for i, event in enumerate(channel_events):
            if not event.is_critical and event.operation.operation_type == OperationType.RWG_LOAD_COEFFS:
                for j in range(i + 1, len(channel_events)):
                    next_event = channel_events[j]
                    if next_event.operation.operation_type == OperationType.RWG_UPDATE_PARAMS:
                        pairs.append(PipelinePair(load_event=event, play_event=next_event))
                        if verbose:
                            print(
                                f"    Found pipeline pair: LOAD@{event.timestamp_cycles}c → PLAY@{next_event.timestamp_cycles}c on {channel.global_id}"
                            )
                        break
    return pairs


def calculate_optimal_schedule(
    events: List[LogicalEvent], pipeline_pairs: List[PipelinePair], verbose: bool = False
) -> List[LogicalEvent]:
    if not pipeline_pairs:
        return events
    events_to_reschedule: Dict[int, int] = {id(p.load_event): 0 for p in pipeline_pairs}
    sorted_pairs = sorted(
        pipeline_pairs,
        key=lambda p: (p.play_start_time, p.channel.global_id),
        reverse=True,
    )
    next_load_available_ts = float("inf")

    for pair in sorted_pairs:
        load_event = pair.load_event
        latest_finish_by = min(pair.play_start_time, next_load_available_ts)
        proposed_start_ts = latest_finish_by - pair.load_cost_cycles

        conflicting_events = []
        for other_event in events:
            if id(other_event) in [id(load_event), id(pair.play_event)]:
                continue
            if id(other_event) in events_to_reschedule:
                continue
            other_start = other_event.timestamp_cycles
            other_end = other_start + (other_event.cost_cycles or 0)
            if (proposed_start_ts < other_end) and (
                (proposed_start_ts + pair.load_cost_cycles) > other_start
            ):
                conflicting_events.append(other_event)

        finish_by = (
            min(e.timestamp_cycles for e in conflicting_events)
            if conflicting_events
            else latest_finish_by
        )
        new_load_ts = finish_by - pair.load_cost_cycles
        events_to_reschedule[id(load_event)] = new_load_ts
        next_load_available_ts = new_load_ts
        if verbose:
            print(
                f"      Scheduling LOAD on {pair.channel.global_id}: {load_event.timestamp_cycles}c → {new_load_ts}c"
            )

    optimized_events = []
    for event in events:
        if id(event) in events_to_reschedule:
            new_timestamp = events_to_reschedule[id(event)]
            optimized_events.append(
                LogicalEvent(
                    timestamp_cycles=new_timestamp,
                    operation=event.operation,
                    oasm_calls=event.oasm_calls,
                    cost_cycles=event.cost_cycles,
                    logical_timestamp=LogicalTimestamp.from_cycles(event.epoch, new_timestamp),
                )
            )
        else:
            optimized_events.append(event)
    return optimized_events


def replace_wait_time_placeholders(
    events_by_board: Dict[OASMAddress, List[LogicalEvent]], verbose: bool = False
) -> None:
    max_end_time = 0
    for events in events_by_board.values():
        for event in events:
            event_end_time = event.timestamp_cycles + (event.cost_cycles if event.cost_cycles else 0)
            max_end_time = max(max_end_time, event_end_time)
    master_wait_time = max_end_time + 100
    for adr, events in events_by_board.items():
        for event in events:
            new_calls = []
            for call in event.oasm_calls:
                if (
                    call.dsl_func == OASMFunction.TRIG_SLAVE
                    and len(call.args) >= 2
                    and call.args[0] == WAIT_TIME_PLACEHOLDER
                ):
                    new_calls.append(
                        OASMCall(
                            adr=call.adr,
                            dsl_func=call.dsl_func,
                            args=(master_wait_time, call.args[1]),
                            kwargs=call.kwargs,
                        )
                    )
                    if verbose:
                        print(
                            f"    Replaced placeholder in {adr.value} with wait time: {master_wait_time} cycles"
                        )
                else:
                    new_calls.append(call)
            event.oasm_calls = new_calls


def generate_scheduled_calls(
    events_by_board: Dict[OASMAddress, List[LogicalEvent]], verbose: bool = False
) -> Dict[OASMAddress, List[OASMCall]]:
    calls_by_board: Dict[OASMAddress, List[OASMCall]] = {}
    for adr, events in events_by_board.items():
        board_calls: List[OASMCall] = []
        if not events:
            calls_by_board[adr] = board_calls
            continue
        sorted_events = sorted(
            events,
            key=lambda e: (
                e.timestamp_cycles,
                0 if e.operation.operation_type == OperationType.RWG_INIT else 1,
                e.operation.channel.global_id if e.operation.channel else "",
            ),
        )
        last_op_end_time = 0
        for event in sorted_events:
            ts = event.timestamp_cycles
            wait_cycles = ts - last_op_end_time
            if wait_cycles < 0:
                wait_cycles = 0
                if event.operation.operation_type == OperationType.OPAQUE_OASM_FUNC:
                    print("  Note: This may be due to a black-box operation occupying the board.")
                    continue
            if wait_cycles > 0:
                board_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.WAIT, args=(wait_cycles,)))
            board_calls.extend(event.oasm_calls)
            actual_start_time = max(ts, last_op_end_time)
            last_op_end_time = actual_start_time + event.cost_cycles
        calls_by_board[adr] = board_calls
    return calls_by_board


def generate_final_calls(
    events_by_board: Dict[OASMAddress, List[LogicalEvent]], verbose: bool = False
) -> Dict[OASMAddress, List[OASMCall]]:
    replace_wait_time_placeholders(events_by_board, verbose=verbose)
    return generate_scheduled_calls(events_by_board, verbose=verbose)
