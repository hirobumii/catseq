"""
Unit tests for structural morphism provenance tracing.
"""

import pytest

from catseq import us
from catseq.atomic import rwg_load_coeffs
from catseq.compilation.pipeline import LogicalEvent, validate_serial_load_constraints
from catseq.compilation.types import OASMAddress
from catseq.debug import format_atomic_trace, trace_index
from catseq.hardware import ttl
from catseq.morphism import identity
from catseq.types.common import Board, Channel, ChannelType, OperationType
from catseq.types.rwg import RWGReady, WaveformParams
from catseq.types.ttl import TTLState


def _waveform() -> WaveformParams:
    return WaveformParams(
        sbg_id=1,
        freq_coeffs=(10.0, 0.1, None, None),
        amp_coeffs=(0.5, 0.01, None, None),
        initial_phase=1.57,
        phase_reset=True,
    )


def _load_piece(channel: Channel, start_state: RWGReady):
    return rwg_load_coeffs(channel, params=[_waveform()], start_state=start_state)


def _first_transfer(channel: Channel, start_state: RWGReady):
    return _load_piece(channel, start_state)


def _second_transfer(channel: Channel, start_state: RWGReady):
    return _load_piece(channel, start_state)


def _extract_load_operations(morphism, channel: Channel):
    return [
        op
        for op in morphism.lanes[channel].operations
        if op.operation_type == OperationType.RWG_LOAD_COEFFS
    ]


def test_trace_distinguishes_different_composition_lines():
    board = Board("rwg0")
    channel = Channel(board, 0, ChannelType.RWG)
    start_state = RWGReady(carrier_freq=100e6)

    morphism = identity(1 * us)
    morphism = morphism >> _first_transfer(channel, start_state)
    morphism = morphism >> _second_transfer(channel, start_state)

    first_load, second_load = _extract_load_operations(morphism, channel)
    first_trace = format_atomic_trace(first_load)
    second_trace = format_atomic_trace(second_load)

    assert "_first_transfer(channel, start_state)" in first_trace
    assert "_second_transfer(channel, start_state)" in second_trace
    assert "compose serial rhs" in first_trace
    assert "compose serial rhs" in second_trace


def test_trace_distinguishes_same_line_loop_iterations_by_compose_id():
    board = Board("rwg0")
    channel = Channel(board, 0, ChannelType.RWG)
    start_state = RWGReady(carrier_freq=100e6)

    morphism = identity(1 * us)
    for _ in range(2): morphism = morphism >> _load_piece(channel, start_state)

    loads = _extract_load_operations(morphism, channel)
    compose_ids = {
        breadcrumb.compose_id
        for load in loads
        for breadcrumb in load.debug_trace
        if breadcrumb.kind == "compose"
        and breadcrumb.compose_kind == "serial"
        and breadcrumb.side == "rhs"
    }

    assert len(compose_ids) == 2


def test_dict_apply_trace_includes_channel_and_source_line():
    board = Board("main")
    channel = Channel(board, 0, ChannelType.TTL)

    morphism = ttl.on()(channel, start_state=TTLState.OFF)
    morphism = morphism >> {channel: ttl.off()}

    off_op = morphism.lanes[channel].operations[-1]
    off_trace = format_atomic_trace(off_op)

    assert "dict apply" in off_trace
    assert channel.global_id in off_trace
    assert "morphism = morphism >> {channel: ttl.off()}" in off_trace


def test_parallel_padding_is_marked_auto_generated():
    left_board = Board("main")
    right_board = Board("rwg0")
    left_channel = Channel(left_board, 0, ChannelType.TTL)
    right_channel = Channel(right_board, 0, ChannelType.TTL)

    left = ttl.on()(left_channel, start_state=TTLState.OFF)
    right = (identity(5 * us) >> ttl.on()(right_channel, start_state=TTLState.OFF))
    morphism = left | right

    padding_op = morphism.lanes[left_channel].operations[-1]

    assert padding_op.operation_type == OperationType.IDENTITY
    assert any(
        breadcrumb.kind == "auto_generated" and breadcrumb.reason == "parallel_padding"
        for breadcrumb in padding_op.debug_trace
    )


def test_serial_load_violation_prints_structural_trace():
    board = Board("rwg0")
    channel = Channel(board, 0, ChannelType.RWG)
    start_state = RWGReady(carrier_freq=100e6)

    morphism = identity(1 * us)
    morphism = morphism >> _first_transfer(channel, start_state)
    morphism = morphism >> _second_transfer(channel, start_state)
    first_load, second_load = _extract_load_operations(morphism, channel)

    first_event = LogicalEvent(timestamp_cycles=100, operation=first_load, cost_cycles=14)
    second_event = LogicalEvent(timestamp_cycles=110, operation=second_load, cost_cycles=14)

    with pytest.raises(ValueError) as exc_info:
        validate_serial_load_constraints(OASMAddress.RWG0, [first_event, second_event])

    message = str(exc_info.value)
    assert "trace:" in message
    assert "_first_transfer(channel, start_state)" in message
    assert "_second_transfer(channel, start_state)" in message
    assert "debug_id=" in message


def test_trace_index_lists_debug_ids():
    board = Board("rwg0")
    channel = Channel(board, 0, ChannelType.RWG)
    start_state = RWGReady(carrier_freq=100e6)
    morphism = _load_piece(channel, start_state)

    index = trace_index(morphism, operation_type=OperationType.RWG_LOAD_COEFFS)

    assert channel.global_id in index
    assert "debug_id=" in index
    assert "RWG_LOAD_COEFFS" in index
