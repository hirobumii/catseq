"""
Rendering helpers for Morphism string and timeline views.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..time_utils import cycles_to_us
from ..types.common import OperationType

if TYPE_CHECKING:
    from ..lanes import Lane
    from ..types.common import AtomicMorphism
    from .core import Morphism


def morphism_str(morphism: "Morphism") -> str:
    if not morphism.lanes:
        if morphism.total_duration_cycles > 0:
            return f"Identity({morphism.total_duration_us:.1f}μs)"
        return "EmptyMorphism"

    board_summary = []
    for board, board_lanes in morphism.lanes_by_board().items():
        channel_list = []
        for channel, lane in sorted(board_lanes.items(), key=lambda x: x[0].local_id):
            channel_list.append(f"ch{channel.local_id}:{lane}")
        board_summary.append(f"{board.id}[{','.join(channel_list)}]")

    return f"⚡ {','.join(board_summary)} ({morphism.total_duration_us:.1f}μs)"


def lanes_view(morphism: "Morphism") -> str:
    if not morphism.lanes:
        if morphism.total_duration_cycles > 0:
            return f"Identity Morphism ({morphism.total_duration_us:.1f}μs)"
        return "Empty Morphism"

    lines = [f"Lanes View ({morphism.total_duration_us:.1f}μs):", "=" * 80]
    sorted_channels = sorted(morphism.lanes.keys(), key=lambda ch: (ch.board.id, ch.local_id))

    for channel in sorted_channels:
        lane = morphism.lanes[channel]
        pulse_pattern = _detect_pulse_pattern(lane)
        if pulse_pattern:
            line = f"{channel.global_id:<20} │ {pulse_pattern}"
        else:
            ops_display = [
                _format_operation_with_state(op, show_state=(i == 0 or i == len(lane.operations) - 1))
                for i, op in enumerate(lane.operations)
            ]
            line = f"{channel.global_id:<20} │ {' → '.join(ops_display)}"
        lines.append(line)

    return "\n".join(lines)


def timeline_view(morphism: "Morphism", compact: bool = True) -> str:
    if not morphism.lanes:
        if morphism.total_duration_cycles > 0:
            return f"Identity Morphism ({morphism.total_duration_us:.1f}μs)"
        return "Empty Morphism"

    lines = [f"Timeline View ({morphism.total_duration_us:.1f}μs):", "=" * 80]
    if compact:
        return _generate_compact_timeline(morphism, lines)
    return _generate_proportional_timeline(morphism, lines)


def _detect_pulse_pattern(lane: "Lane") -> str | None:
    ops = lane.operations
    if (
        len(ops) == 3
        and ops[0].operation_type == OperationType.TTL_ON
        and ops[1].operation_type == OperationType.IDENTITY
        and ops[2].operation_type == OperationType.TTL_OFF
    ):
        return f"🔲 TTL_pulse({cycles_to_us(ops[1].duration_cycles):.1f}μs)"

    if (
        len(ops) == 3
        and ops[0].operation_type == OperationType.RWG_RF_SWITCH
        and ops[1].operation_type == OperationType.IDENTITY
        and ops[2].operation_type == OperationType.RWG_RF_SWITCH
    ):
        if (
            hasattr(ops[0].start_state, "rf_on")
            and hasattr(ops[0].end_state, "rf_on")
            and hasattr(ops[2].start_state, "rf_on")
            and hasattr(ops[2].end_state, "rf_on")
            and (not ops[0].start_state.rf_on)
            and ops[0].end_state.rf_on
            and ops[2].start_state.rf_on
            and (not ops[2].end_state.rf_on)
        ):
            return f"📡 RF_pulse({cycles_to_us(ops[1].duration_cycles):.1f}μs)"
    return None


def _format_operation_with_state(op: "AtomicMorphism", show_state: bool = False) -> str:
    duration_us = cycles_to_us(op.duration_cycles)
    op_name = {
        OperationType.TTL_INIT: "init",
        OperationType.TTL_ON: "ON",
        OperationType.TTL_OFF: "OFF",
        OperationType.RWG_INIT: "init",
        OperationType.RWG_SET_CARRIER: "set_carrier",
        OperationType.RWG_LOAD_COEFFS: "load",
        OperationType.RWG_UPDATE_PARAMS: "play",
        OperationType.RWG_RF_SWITCH: "rf_switch",
        OperationType.IDENTITY: "wait",
        OperationType.SYNC_MASTER: "sync_master",
        OperationType.SYNC_SLAVE: "sync_slave",
    }.get(op.operation_type, str(op.operation_type))

    op_display = f"{op_name}({duration_us:.1f}μs)" if duration_us > 0 else op_name
    if show_state and hasattr(op.end_state, "rf_on"):
        rf_status = "RF_ON" if op.end_state.rf_on else "RF_OFF"
        op_display += f"[{rf_status}]"
    elif show_state and op.end_state and hasattr(op.end_state, "name"):
        op_display += f"[{op.end_state.name}]"
    return op_display


def _generate_compact_timeline(morphism: "Morphism", lines: list[str]) -> str:
    events = []
    sorted_channels = sorted(morphism.lanes.keys(), key=lambda ch: (ch.board.id, ch.local_id))

    for channel in sorted_channels:
        lane = morphism.lanes[channel]
        current_time = 0.0
        for op in lane.operations:
            if op.operation_type != OperationType.IDENTITY:
                events.append({"time": current_time, "channel": channel, "operation": op, "type": "instant"})
            else:
                events.append(
                    {
                        "time": current_time,
                        "channel": channel,
                        "operation": op,
                        "duration": cycles_to_us(op.duration_cycles),
                        "type": "wait",
                    }
                )
            current_time += cycles_to_us(op.duration_cycles)

    events.sort(key=lambda e: (e["time"], e["channel"].global_id))
    time_markers = [_format_time(t) for t in sorted(set(e["time"] for e in events))[:10]]
    lines.append("Events: " + " → ".join(time_markers))
    lines.append("")

    for channel in sorted_channels:
        channel_events = [e for e in events if e["channel"] == channel]
        timeline_parts = []
        for event in channel_events:
            if event["type"] == "instant":
                timeline_parts.append(f"t={_format_time(event['time'])}:{_get_operation_symbol(event['operation'])}")
            elif event["duration"] > 0.1:
                timeline_parts.append(f"⏳({_format_time(event['duration'])})")
        if timeline_parts:
            lines.append(f"{channel.global_id:<9} │ {' → '.join(timeline_parts)}")
    return "\n".join(lines)


def _generate_proportional_timeline(morphism: "Morphism", lines: list[str]) -> str:
    total_us = morphism.total_duration_us
    max_chars = 100
    resolution_us = 1.0 if total_us <= 100 else 10.0 if total_us <= 1000 else total_us / max_chars
    time_steps = int(total_us / resolution_us)
    if time_steps > max_chars:
        return _generate_compact_timeline(morphism, lines)

    time_markers = [_format_time(i * resolution_us) for i in range(0, min(time_steps, 10))]
    lines.append("Time: " + " ".join(f"{marker:>8}" for marker in time_markers))
    lines.append(" " * 6 + "─" * min(time_steps, max_chars))

    sorted_channels = sorted(morphism.lanes.keys(), key=lambda ch: (ch.board.id, ch.local_id))
    for channel in sorted_channels:
        lines.append(
            f"{channel.global_id:<9} │{_generate_channel_timeline(morphism.lanes[channel], total_us, resolution_us)}"
        )
    return "\n".join(lines)


def _get_operation_symbol(op: "AtomicMorphism") -> str:
    symbol_map = {
        OperationType.TTL_ON: "▲",
        OperationType.TTL_OFF: "▼",
        OperationType.TTL_INIT: "◇",
        OperationType.RWG_INIT: "◆",
        OperationType.RWG_SET_CARRIER: "🔶",
        OperationType.RWG_LOAD_COEFFS: "📥",
        OperationType.RWG_UPDATE_PARAMS: "▶️",
        OperationType.SYNC_MASTER: "🔄",
        OperationType.SYNC_SLAVE: "🔃",
    }
    if op.operation_type == OperationType.RWG_RF_SWITCH:
        return "📡" if hasattr(op.end_state, "rf_on") and op.end_state.rf_on else "📴"
    return symbol_map.get(op.operation_type, "●")


def _format_time(time_us: float) -> str:
    if time_us < 1:
        return f"{time_us:.1f}μs"
    if time_us < 1000:
        return f"{time_us:.0f}μs"
    if time_us < 1000000:
        return f"{time_us / 1000:.1f}ms"
    return f"{time_us / 1000000:.1f}s"


def _generate_channel_timeline(lane: "Lane", total_us: float, resolution_us: float) -> str:
    timeline_length = max(1, int(total_us / resolution_us)) * 8
    timeline = [" "] * timeline_length
    current_time_us = 0.0

    for op in lane.operations:
        op_duration_us = cycles_to_us(op.duration_cycles)
        start_pos = int(current_time_us / resolution_us) * 8
        end_pos = int((current_time_us + op_duration_us) / resolution_us) * 8

        if op.operation_type == OperationType.TTL_ON:
            symbol = "▲"
        elif op.operation_type == OperationType.TTL_OFF:
            symbol = "▼"
        elif op.operation_type == OperationType.RWG_RF_SWITCH:
            symbol = "◆" if hasattr(op.end_state, "rf_on") and op.end_state.rf_on else "◇"
        elif op.operation_type == OperationType.IDENTITY:
            symbol = "─"
        else:
            symbol = "●"

        if op.operation_type == OperationType.IDENTITY:
            for pos in range(start_pos, min(end_pos, timeline_length)):
                timeline[pos] = symbol
        elif start_pos < timeline_length:
            timeline[start_pos] = symbol

        current_time_us += op_duration_us

    return "".join(timeline)
