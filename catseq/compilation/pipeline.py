"""
Compiler pipeline internals.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from ..debug import format_event_trace
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
    blackbox_group_id: int | None = None
    blackbox_board: str | None = None

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
        return self.play_event.effective_timestamp_cycles

    @property
    def epoch(self) -> int:
        return self.load_event.epoch


def _is_sync_event(event: LogicalEvent) -> bool:
    return event.operation.operation_type in {OperationType.SYNC_MASTER, OperationType.SYNC_SLAVE}


def _event_offset(event: LogicalEvent) -> int:
    return event.logical_timestamp.time_offset_cycles


def _event_priority(event: LogicalEvent) -> int:
    if event.operation.operation_type == OperationType.RWG_INIT:
        return 0
    if _is_sync_event(event):
        return 2
    return 1


def _sorted_epoch_events(events: List[LogicalEvent]) -> List[LogicalEvent]:
    return sorted(
        events,
        key=lambda e: (
            e.epoch,
            _event_offset(e),
            _event_priority(e),
            e.operation.channel.global_id if e.operation.channel else "",
        ),
    )

def _describe_event(event: LogicalEvent) -> str:
    channel_id = event.operation.channel.global_id if event.operation.channel is not None else "<board>"
    return (
        f"{event.operation.operation_type.name} on {channel_id} "
        f"(epoch={event.epoch}, offset={_event_offset(event)}c, raw={event.timestamp_cycles}c, "
        f"cost={event.cost_cycles}c, debug_id={event.operation.debug_id})"
    )


def _events_by_timestamp(events: List[LogicalEvent]) -> List[tuple[int, List[LogicalEvent]]]:
    grouped: Dict[int, List[LogicalEvent]] = {}
    for event in events:
        grouped.setdefault(event.timestamp_cycles, []).append(event)
    return [(timestamp, grouped[timestamp]) for timestamp in sorted(grouped)]


def _pending_waveforms(event: LogicalEvent):
    if event.operation.operation_type != OperationType.RWG_LOAD_COEFFS:
        return ()
    end_state = getattr(event.operation, "end_state", None)
    return getattr(end_state, "pending_waveforms", ()) or ()


def _is_zero_or_none(value) -> bool:
    return value is None or value == 0 or value == 0.0


def _is_static_terminal_load(event: LogicalEvent) -> bool:
    waveforms = _pending_waveforms(event)
    if not waveforms:
        return False
    return all(
        waveform.phase_reset is False
        and _is_zero_or_none(waveform.freq_coeffs[1])
        and _is_zero_or_none(waveform.amp_coeffs[1])
        for waveform in waveforms
    )


def _is_ramping_load(event: LogicalEvent) -> bool:
    waveforms = _pending_waveforms(event)
    if not waveforms:
        return False
    return any(
        waveform.phase_reset is False
        and (
            not _is_zero_or_none(waveform.freq_coeffs[1])
            or not _is_zero_or_none(waveform.amp_coeffs[1])
        )
        for waveform in waveforms
    )


def _same_snapshot(left, right) -> bool:
    left_snapshot = getattr(left.operation.end_state, "snapshot", None)
    right_snapshot = getattr(right.operation.start_state, "snapshot", None)
    return left_snapshot == right_snapshot


def _fuse_zero_gap_ramp_handoffs(events_by_board: Dict[OASMAddress, List[LogicalEvent]]) -> None:
    for adr, events in events_by_board.items():
        del adr
        indexed_events = list(enumerate(events))
        events_by_channel: Dict[Channel, List[tuple[int, LogicalEvent]]] = {}
        for index, event in indexed_events:
            channel = event.operation.channel
            if channel is None:
                continue
            events_by_channel.setdefault(channel, []).append((index, event))

        indices_to_remove: set[int] = set()
        for channel_events in events_by_channel.values():
            i = 0
            while i + 3 < len(channel_events):
                load_static_idx, load_static = channel_events[i]
                play_static_idx, play_static = channel_events[i + 1]
                load_ramp_idx, load_ramp = channel_events[i + 2]
                play_ramp_idx, play_ramp = channel_events[i + 3]

                if (
                    load_static.operation.operation_type == OperationType.RWG_LOAD_COEFFS
                    and play_static.operation.operation_type == OperationType.RWG_UPDATE_PARAMS
                    and load_ramp.operation.operation_type == OperationType.RWG_LOAD_COEFFS
                    and play_ramp.operation.operation_type == OperationType.RWG_UPDATE_PARAMS
                    and _is_static_terminal_load(load_static)
                    and _is_ramping_load(load_ramp)
                    and load_static.operation.channel == play_static.operation.channel
                    == load_ramp.operation.channel
                    == play_ramp.operation.channel
                    and play_static.timestamp_cycles == load_ramp.timestamp_cycles
                    and _same_snapshot(play_static, load_ramp)
                ):
                    indices_to_remove.add(load_static_idx)
                    indices_to_remove.add(play_static_idx)
                    i += 2
                    continue

                i += 1

        if indices_to_remove:
            events[:] = [
                event for index, event in indexed_events if index not in indices_to_remove
            ]


def _events_by_epoch(events: List[LogicalEvent]) -> Dict[int, List[LogicalEvent]]:
    grouped: Dict[int, List[LogicalEvent]] = {}
    for event in events:
        grouped.setdefault(event.epoch, []).append(event)
    for epoch in grouped:
        grouped[epoch].sort(
            key=lambda e: (
                e.timestamp_cycles,
                _event_priority(e),
                e.operation.channel.global_id if e.operation.channel else "",
            )
        )
    return grouped


def _opaque_signature(event: LogicalEvent) -> tuple[int, repr, repr, int]:
    op = event.operation
    if not isinstance(op, BlackBoxAtomicMorphism):
        raise TypeError("opaque signature requested for non-blackbox event")
    return (id(op.user_func), repr(op.user_args), repr(op.user_kwargs), op.duration_cycles)


def _collapse_board_scoped_blackboxes(
    adr: OASMAddress, events: List[LogicalEvent]
) -> List[LogicalEvent]:
    collapsed: List[LogicalEvent] = []
    for timestamp, cohort in _events_by_timestamp(events):
        opaque = [e for e in cohort if isinstance(e.operation, BlackBoxAtomicMorphism)]
        non_opaque = [e for e in cohort if not isinstance(e.operation, BlackBoxAtomicMorphism)]
        collapsed.extend(non_opaque)
        if not opaque:
            continue

        groups: Dict[tuple[int, repr, repr, int], List[LogicalEvent]] = {}
        for event in opaque:
            groups.setdefault(_opaque_signature(event), []).append(event)

        for signature, group in groups.items():
            rep = sorted(
                group,
                key=lambda e: e.operation.channel.global_id if e.operation.channel else "",
            )[0]
            synthetic_op = rep.operation.with_channel_and_states(None, None, None)
            collapsed.append(
                LogicalEvent(
                    timestamp_cycles=timestamp,
                    operation=synthetic_op,
                    cost_cycles=rep.cost_cycles,
                    is_critical=True,
                    logical_timestamp=rep.logical_timestamp,
                    blackbox_group_id=hash((signature[0], signature[1], signature[2], timestamp)),
                    blackbox_board=adr.value,
                )
            )
    collapsed.sort(
        key=lambda e: (
            e.timestamp_cycles,
            _event_priority(e),
            e.operation.channel.global_id if e.operation.channel else "",
        )
    )
    return collapsed


def _sync_role_for_cohort(
    adr: OASMAddress, timestamp: int, cohort: List[LogicalEvent]
) -> OperationType | None:
    sync_roles = {
        event.operation.operation_type for event in cohort if _is_sync_event(event)
    }
    if not sync_roles:
        return None
    if len(sync_roles) > 1:
        raise ValueError(
            f"Invalid sync boundary on board {adr.value} at t={timestamp}c: "
            "mixed SYNC_MASTER and SYNC_SLAVE operations in one local sync cohort."
        )
    return next(iter(sync_roles))


def _discover_sync_rounds(
    events_by_board: Dict[OASMAddress, List[LogicalEvent]]
) -> Dict[OASMAddress, List[int]]:
    sync_rounds_by_board: Dict[OASMAddress, List[tuple[int, OperationType]]] = {}
    for adr, events in events_by_board.items():
        board_rounds: List[tuple[int, OperationType]] = []
        for timestamp, cohort in _events_by_timestamp(events):
            role = _sync_role_for_cohort(adr, timestamp, cohort)
            if role is not None:
                board_rounds.append((timestamp, role))
        sync_rounds_by_board[adr] = board_rounds

    if not any(sync_rounds_by_board.values()):
        return {adr: [] for adr in events_by_board}

    expected_rounds = len(next(rounds for rounds in sync_rounds_by_board.values() if rounds))
    for adr, rounds in sync_rounds_by_board.items():
        if len(rounds) != expected_rounds:
            raise ValueError(
                "Incomplete global sync boundary: every active board must participate in each "
                f"sync round. Board {adr.value} has {len(rounds)} sync round(s), expected {expected_rounds}."
            )

    for round_index in range(expected_rounds):
        master_boards = [
            adr
            for adr, rounds in sync_rounds_by_board.items()
            if rounds[round_index][1] == OperationType.SYNC_MASTER
        ]
        slave_boards = [
            adr
            for adr, rounds in sync_rounds_by_board.items()
            if rounds[round_index][1] == OperationType.SYNC_SLAVE
        ]
        if len(master_boards) != 1 or not slave_boards:
            raise ValueError(
                "Invalid global sync boundary: each sync round must contain exactly one master "
                f"board and at least one slave board. Round {round_index} has "
                f"{len(master_boards)} master board(s) and {len(slave_boards)} slave board(s)."
            )

    return {
        adr: [timestamp for timestamp, _role in rounds]
        for adr, rounds in sync_rounds_by_board.items()
    }


def detect_epoch_boundaries(events_by_board: Dict[OASMAddress, List[LogicalEvent]]) -> None:
    sync_rounds_by_board = _discover_sync_rounds(events_by_board)
    for adr, events in events_by_board.items():
        current_epoch = 0
        epoch_base_timestamp = 0
        sync_timestamps = set(sync_rounds_by_board[adr])
        for timestamp, cohort in _events_by_timestamp(events):
            for event in cohort:
                event.logical_timestamp = LogicalTimestamp.from_cycles(
                    current_epoch,
                    timestamp - epoch_base_timestamp,
                )
            if timestamp in sync_timestamps:
                current_epoch += 1
                epoch_base_timestamp = timestamp


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
        collapsed = _collapse_board_scoped_blackboxes(adr, events)
        events_by_board[adr] = collapsed
        collapsed.sort(
            key=lambda e: (
                e.timestamp_cycles,
                _event_priority(e),
                e.operation.channel.global_id if e.operation.channel else "",
            )
        )
        _translate_board_events(adr, collapsed)

    _fuse_zero_gap_ramp_handoffs(events_by_board)

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
            first_sig = (
                id(first_op.user_func),
                repr(first_op.user_args),
                repr(first_op.user_kwargs),
                first_op.duration_cycles,
            )
            for other_event in opaque_events[1:]:
                other_op = other_event.operation
                other_sig = (
                    id(other_op.user_func),
                    repr(other_op.user_args),
                    repr(other_op.user_kwargs),
                    other_op.duration_cycles,
                )
                if other_sig != first_sig:
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
    detect_epoch_boundaries(events_by_board)

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
        optimized_events: List[LogicalEvent] = []
        for epoch in sorted(_events_by_epoch(events)):
            epoch_events = _events_by_epoch(events)[epoch]
            pipeline_pairs = identify_pipeline_pairs(epoch_events, verbose=verbose)
            if pipeline_pairs:
                epoch_events = calculate_optimal_schedule(
                    epoch_events, pipeline_pairs, verbose=verbose
                )
            optimized_events.extend(epoch_events)
        events_by_board[adr] = optimized_events
    detect_epoch_boundaries(events_by_board)


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
    validate_blackbox_group_coherence(events_by_board, verbose=verbose)
    for adr, events in events_by_board.items():
        validate_serial_load_constraints(adr, events, verbose=verbose)
        validate_load_deadlines(adr, events, verbose=verbose)
        validate_rwg_load_play_ownership(adr, events, verbose=verbose)
        validate_timing_consistency(adr, events, verbose=verbose)
        check_cross_epoch_violations_single_board(adr, events, verbose=verbose)
        validate_black_box_exclusivity(adr, events, verbose=verbose)


def validate_blackbox_group_coherence(
    events_by_board: Dict[OASMAddress, List[LogicalEvent]], verbose: bool = False
):
    groups: Dict[int, List[LogicalEvent]] = {}
    for events in events_by_board.values():
        for event in events:
            if event.blackbox_group_id is not None:
                groups.setdefault(event.blackbox_group_id, []).append(event)

    for group_id, grouped in groups.items():
        timestamps = {event.timestamp_cycles for event in grouped}
        durations = {event.operation.duration_cycles for event in grouped}
        if len(timestamps) > 1:
            raise ValueError(
                f"Black-box group {group_id} has inconsistent start times across boards: {sorted(timestamps)}"
            )
        if len(durations) > 1:
            raise ValueError(
                f"Black-box group {group_id} has inconsistent durations across boards: {sorted(durations)}"
            )


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
    for epoch, epoch_events in _events_by_epoch(load_events).items():
        del epoch
        for i in range(len(epoch_events) - 1):
            current_load = epoch_events[i]
            next_load = epoch_events[i + 1]
            current_end = current_load.timestamp_cycles + (current_load.cost_cycles or 0)
            next_start = next_load.timestamp_cycles
            if next_start < current_end:
                raise ValueError(
                    f"Serial constraint violation on board {adr.value}: "
                    f"LOAD operations overlap - load1 ends at {current_end}c, load2 starts at {next_start}c\n"
                    f"  load1: {_describe_event(current_load)}\n"
                    f"{format_event_trace(current_load, indent='    ')}\n"
                    f"  load2: {_describe_event(next_load)}\n"
                    f"{format_event_trace(next_load, indent='    ')}"
                )


def validate_load_deadlines(adr, events: List[LogicalEvent], verbose: bool = False):
    load_events = [e for e in events if e.operation.operation_type == OperationType.RWG_LOAD_COEFFS]
    play_events = [e for e in events if e.operation.operation_type == OperationType.RWG_UPDATE_PARAMS]
    if not load_events or not play_events:
        return
    for epoch in sorted({event.epoch for event in events}):
        epoch_loads = [e for e in load_events if e.epoch == epoch]
        epoch_plays = [e for e in play_events if e.epoch == epoch]
        for pair in identify_load_play_pairs(epoch_loads, epoch_plays):
            load_event = pair["load_event"]
            play_event = pair["play_event"]
            load_end = load_event.timestamp_cycles + (load_event.cost_cycles or 0)
            play_start = play_event.timestamp_cycles
            if load_end > play_start:
                raise ValueError(
                    f"Deadline violation on board {adr.value}: "
                    f"LOAD operation ends at {load_end}c but PLAY starts at {play_start}c"
                )


def validate_rwg_load_play_ownership(adr, events: List[LogicalEvent], verbose: bool = False):
    for epoch, epoch_events in _events_by_epoch(events).items():
        for index, event in enumerate(epoch_events):
            if event.operation.operation_type != OperationType.RWG_UPDATE_PARAMS:
                continue

            channel = event.operation.channel
            preceding_load = None
            for prev in reversed(epoch_events[:index]):
                if (
                    prev.operation.operation_type == OperationType.RWG_LOAD_COEFFS
                    and prev.operation.channel == channel
                ):
                    preceding_load = prev
                    break

            if preceding_load is None:
                continue

            for between in epoch_events:
                if between is preceding_load or between is event:
                    continue
                if not (
                    preceding_load.timestamp_cycles < between.timestamp_cycles < event.timestamp_cycles
                ):
                    continue
                if (
                    between.operation.operation_type == OperationType.RWG_LOAD_COEFFS
                    and between.operation.channel == channel
                ):
                    raise ValueError(
                        f"RWG load/play ownership violation on board {adr.value}: "
                        f"{between.operation.operation_type.name} at {between.timestamp_cycles}c "
                        f"intervenes between paired LOAD on {channel.global_id} at "
                        f"{preceding_load.timestamp_cycles}c and PLAY at {event.timestamp_cycles}c "
                        f"(epoch {epoch})"
                    )


def validate_timing_consistency(adr, events: List[LogicalEvent], verbose: bool = False):
    for event in events:
        if event.timestamp_cycles < 0:
            raise ValueError(
                f"Timing consistency violation on board {adr.value}: "
                f"Event has negative timestamp: {event.timestamp_cycles}c"
            )
    sorted_events = sorted(events, key=lambda x: (x.epoch, _event_offset(x)))
    prev_epoch = 0
    prev_time = 0
    for event in sorted_events:
        if event.epoch != prev_epoch:
            prev_epoch = event.epoch
            prev_time = 0
        event_offset = _event_offset(event)
        if event_offset < prev_time:
            raise ValueError(
                f"Timing consistency violation on board {adr.value}: "
                "Events are not properly ordered in time"
            )
        prev_time = event_offset


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
                and next_event.logical_timestamp.time_offset_cycles < (next_event.cost_cycles or 0)
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
        channel_events.sort(key=lambda e: (e.epoch, e.timestamp_cycles))
        for i, event in enumerate(channel_events):
            if not event.is_critical and event.operation.operation_type == OperationType.RWG_LOAD_COEFFS:
                for j in range(i + 1, len(channel_events)):
                    next_event = channel_events[j]
                    if next_event.epoch != event.epoch:
                        break
                    if next_event.operation.operation_type == OperationType.RWG_UPDATE_PARAMS:
                        pairs.append(PipelinePair(load_event=event, play_event=next_event))
                        if verbose:
                            print(
                                f"    Found pipeline pair: LOAD@e{event.epoch}:{_event_offset(event)}c → PLAY@e{next_event.epoch}:{_event_offset(next_event)}c on {channel.global_id}"
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
        key=lambda p: (p.play_event.timestamp_cycles, p.channel.global_id),
        reverse=True,
    )
    next_load_available_ts = float("inf")

    for pair in sorted_pairs:
        load_event = pair.load_event
        latest_finish_by = min(pair.play_event.timestamp_cycles, next_load_available_ts)
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
        new_load_ts = max(0, finish_by - pair.load_cost_cycles)
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
                    is_critical=event.is_critical,
                    logical_timestamp=event.logical_timestamp,
                )
            )
        else:
            optimized_events.append(event)
    return optimized_events


def replace_wait_time_placeholders(
    events_by_board: Dict[OASMAddress, List[LogicalEvent]], verbose: bool = False
) -> None:
    sync_frontiers: Dict[int, Dict[OASMAddress, int]] = {}

    for adr, events in events_by_board.items():
        sorted_events = _sorted_epoch_events(events)
        current_epoch = None
        last_op_end_time = 0
        for event in sorted_events:
            if current_epoch != event.epoch:
                current_epoch = event.epoch
                last_op_end_time = 0
            actual_start = max(_event_offset(event), last_op_end_time)
            if _is_sync_event(event):
                sync_frontiers.setdefault(event.epoch, {})[adr] = actual_start
            last_op_end_time = actual_start + (event.cost_cycles or 0)

    for adr, events in events_by_board.items():
        for event in events:
            new_calls = []
            for call in event.oasm_calls:
                if (
                    call.dsl_func == OASMFunction.TRIG_SLAVE
                    and len(call.args) >= 2
                    and call.args[0] == WAIT_TIME_PLACEHOLDER
                ):
                    epoch_frontiers = sync_frontiers.get(event.epoch, {})
                    if not epoch_frontiers:
                        master_wait_time = 100
                    else:
                        sync_offset = _event_offset(event)
                        frontier_time = max(epoch_frontiers.values())
                        master_wait_time = max(0, frontier_time - sync_offset) + 100
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
                            f"    Replaced placeholder in {adr.value} epoch {event.epoch} with wait time: {master_wait_time} cycles"
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
        sorted_events = _sorted_epoch_events(events)
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
