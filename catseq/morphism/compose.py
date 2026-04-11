"""
Morphism composition algorithms.
"""

from __future__ import annotations

from ..lanes import Lane
from ..time_utils import cycles_to_time
from ..types.common import AtomicMorphism, OperationType
from ..types.ttl import TTLState
from .core import Morphism, identity


def strict_compose_morphisms(first: Morphism, second: Morphism) -> Morphism:
    """严格状态匹配组合 (@)"""
    first_end_states = {}
    for channel, lane in first.lanes.items():
        if lane.operations and lane.operations[-1].operation_type != OperationType.IDENTITY:
            first_end_states[channel] = lane.end_state

    second_start_states = {}
    for channel, lane in second.lanes.items():
        if lane.operations and lane.operations[0].operation_type != OperationType.IDENTITY:
            second_start_states[channel] = lane.initial_state

    for channel in first_end_states:
        if channel in second_start_states and first_end_states[channel] != second_start_states[channel]:
            raise ValueError(
                f"State mismatch for channel {channel}: "
                f"{first_end_states[channel]} → {second_start_states[channel]}"
            )

    result_lanes = {}
    all_channels = set(first.lanes.keys()) | set(second.lanes.keys())

    for channel in all_channels:
        first_ops = first.lanes.get(channel, Lane(())).operations
        second_ops = second.lanes.get(channel, Lane(())).operations

        if channel not in first.lanes:
            duration = first.total_duration_cycles
            identity_op = AtomicMorphism(
                channel,
                second_start_states[channel],
                second_start_states[channel],
                duration,
                OperationType.IDENTITY,
            )
            first_ops = (identity_op,)

        if channel not in second.lanes:
            duration = second.total_duration_cycles
            identity_op = AtomicMorphism(
                channel,
                first_end_states[channel],
                first_end_states[channel],
                duration,
                OperationType.IDENTITY,
            )
            second_ops = (identity_op,)

        result_lanes[channel] = Lane(first_ops + second_ops)

    return Morphism(result_lanes)


def auto_compose_morphisms(first: Morphism, second: Morphism) -> Morphism:
    """自动状态推断组合 (>>)"""
    if not second.lanes:
        return first

    first_end_states = {}
    for channel, lane in first.lanes.items():
        if lane.effective_end_state is not None:
            first_end_states[channel] = lane.effective_end_state
        elif lane.initial_state is not None:
            first_end_states[channel] = lane.initial_state

    result_lanes = {}
    all_channels = set(first.lanes.keys()) | set(second.lanes.keys())

    for channel in all_channels:
        first_ops = first.lanes.get(channel, Lane(())).operations
        second_ops = second.lanes.get(channel, Lane(())).operations

        if channel not in first.lanes and channel in second.lanes:
            first_state = second.lanes[channel].operations[0].start_state
            duration = first.total_duration_cycles
            identity_op = AtomicMorphism(
                channel, first_state, first_state, duration, OperationType.IDENTITY
            )
            first_ops = (identity_op,)
        elif channel not in second.lanes and channel in first.lanes:
            end_state = first_end_states[channel]
            duration = second.total_duration_cycles
            identity_op = AtomicMorphism(
                channel, end_state, end_state, duration, OperationType.IDENTITY
            )
            second_ops = (identity_op,)

        new_second_ops = []
        ops_iterator = iter(second_ops)
        for op in ops_iterator:
            if op.operation_type == OperationType.IDENTITY:
                inferred_state = first_end_states.get(channel, TTLState.OFF)
                new_second_ops.append(
                    AtomicMorphism(
                        op.channel if op.channel else channel,
                        inferred_state,
                        inferred_state,
                        op.duration_cycles,
                        op.operation_type,
                    )
                )
            else:
                new_second_ops.append(op)
                new_second_ops.extend(ops_iterator)
                break
        second_ops = tuple(new_second_ops)

        result_lanes[channel] = Lane(first_ops + second_ops)

    return Morphism(result_lanes)


def parallel_compose_morphisms(left: Morphism, right: Morphism) -> Morphism:
    """并行组合操作 (|)"""
    overlapping_channels = set(left.lanes.keys()) & set(right.lanes.keys())
    if overlapping_channels:
        channel_names = [ch.global_id for ch in overlapping_channels]
        raise ValueError(f"Cannot compose: overlapping channels {channel_names}")

    left_duration = left.total_duration_cycles
    right_duration = right.total_duration_cycles

    if left_duration == right_duration:
        return Morphism({**left.lanes, **right.lanes})

    if left_duration < right_duration:
        padding_seconds = cycles_to_time(right_duration - left_duration)
        left = left >> identity(padding_seconds)
    elif right_duration < left_duration:
        padding_seconds = cycles_to_time(left_duration - right_duration)
        right = right >> identity(padding_seconds)

    return Morphism({**left.lanes, **right.lanes})
