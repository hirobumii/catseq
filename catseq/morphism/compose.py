"""
Morphism composition algorithms.
"""

from __future__ import annotations

from ..expr import Expr, structurally_equal
from ..debug import annotate_morphism, auto_generated_breadcrumb
from ..lanes import Lane
from ..types.common import AtomicMorphism, DebugBreadcrumb, OperationType, TimingKind
from ..types.ttl import TTLState
from .core import Morphism


def strict_compose_morphisms(
    first: Morphism,
    second: Morphism,
    *,
    lhs_breadcrumb: DebugBreadcrumb | None = None,
    rhs_breadcrumb: DebugBreadcrumb | None = None,
) -> Morphism:
    """严格状态匹配组合 (@)"""
    if lhs_breadcrumb is not None:
        first = annotate_morphism(first, (lhs_breadcrumb,))
    if rhs_breadcrumb is not None:
        second = annotate_morphism(second, (rhs_breadcrumb,))

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
            duration = first.total_duration_expr
            identity_op = AtomicMorphism(
                channel,
                second_start_states[channel],
                second_start_states[channel],
                duration,
                OperationType.IDENTITY,
                timing_kind=TimingKind.DELAY,
                debug_trace=(
                    auto_generated_breadcrumb("strict_compose_missing_lhs_channel"),
                )
                + ((lhs_breadcrumb,) if lhs_breadcrumb is not None else ()),
            )
            first_ops = (identity_op,)

        if channel not in second.lanes:
            duration = second.total_duration_expr
            identity_op = AtomicMorphism(
                channel,
                first_end_states[channel],
                first_end_states[channel],
                duration,
                OperationType.IDENTITY,
                timing_kind=TimingKind.DELAY,
                debug_trace=(
                    auto_generated_breadcrumb("strict_compose_missing_rhs_channel"),
                )
                + ((rhs_breadcrumb,) if rhs_breadcrumb is not None else ()),
            )
            second_ops = (identity_op,)

        result_lanes[channel] = Lane(first_ops + second_ops)

    return Morphism(result_lanes)


def auto_compose_morphisms(
    first: Morphism,
    second: Morphism,
    *,
    lhs_breadcrumb: DebugBreadcrumb | None = None,
    rhs_breadcrumb: DebugBreadcrumb | None = None,
) -> Morphism:
    """自动状态推断组合 (>>)"""
    if lhs_breadcrumb is not None:
        first = annotate_morphism(first, (lhs_breadcrumb,))
    if rhs_breadcrumb is not None:
        second = annotate_morphism(second, (rhs_breadcrumb,))
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
            duration = first.total_duration_expr
            identity_op = AtomicMorphism(
                channel,
                first_state,
                first_state,
                duration,
                OperationType.IDENTITY,
                timing_kind=TimingKind.DELAY,
                debug_trace=(
                    auto_generated_breadcrumb("auto_compose_missing_lhs_channel"),
                )
                + ((lhs_breadcrumb,) if lhs_breadcrumb is not None else ()),
            )
            first_ops = (identity_op,)
        elif channel not in second.lanes and channel in first.lanes:
            end_state = first_end_states[channel]
            duration = second.total_duration_expr
            identity_op = AtomicMorphism(
                channel,
                end_state,
                end_state,
                duration,
                OperationType.IDENTITY,
                timing_kind=TimingKind.DELAY,
                debug_trace=(
                    auto_generated_breadcrumb("auto_compose_missing_rhs_channel"),
                )
                + ((rhs_breadcrumb,) if rhs_breadcrumb is not None else ()),
            )
            second_ops = (identity_op,)

        new_second_ops = []
        ops_iterator = iter(second_ops)
        for op in ops_iterator:
            if op.operation_type == OperationType.IDENTITY:
                inferred_state = first_end_states.get(channel, TTLState.OFF)
                new_second_ops.append(
                    op.with_channel_and_states(
                        op.channel if op.channel is not None else channel,
                        inferred_state,
                        inferred_state,
                    )
                )
            else:
                new_second_ops.append(op)
                new_second_ops.extend(ops_iterator)
                break
        second_ops = tuple(new_second_ops)

        result_lanes[channel] = Lane(first_ops + second_ops)

    return Morphism(result_lanes)


def parallel_compose_morphisms(
    left: Morphism,
    right: Morphism,
    *,
    lhs_breadcrumb: DebugBreadcrumb | None = None,
    rhs_breadcrumb: DebugBreadcrumb | None = None,
) -> Morphism:
    """并行组合操作 (|)"""
    if lhs_breadcrumb is not None:
        left = annotate_morphism(left, (lhs_breadcrumb,))
    if rhs_breadcrumb is not None:
        right = annotate_morphism(right, (rhs_breadcrumb,))

    overlapping_channels = set(left.lanes.keys()) & set(right.lanes.keys())
    if overlapping_channels:
        channel_names = [ch.global_id for ch in overlapping_channels]
        raise ValueError(f"Cannot compose: overlapping channels {channel_names}")

    left_duration = left.total_duration_expr
    right_duration = right.total_duration_expr

    if structurally_equal(left_duration, right_duration):
        return Morphism({**left.lanes, **right.lanes})

    if isinstance(left_duration, Expr) or isinstance(right_duration, Expr):
        raise TypeError(
            "Parallel composition requires concrete or structurally equal durations. "
            "Realize symbolic durations first."
        )

    if left_duration < right_duration:
        left = _pad_parallel_side(
            left,
            right_duration,
            auto_generated_breadcrumb("parallel_padding"),
            lhs_breadcrumb,
        )
    elif right_duration < left_duration:
        right = _pad_parallel_side(
            right,
            left_duration,
            auto_generated_breadcrumb("parallel_padding"),
            rhs_breadcrumb,
        )

    return Morphism({**left.lanes, **right.lanes})


def _pad_parallel_side(
    morphism: Morphism,
    target_duration_cycles: int | Expr,
    auto_breadcrumb: DebugBreadcrumb,
    compose_breadcrumb: DebugBreadcrumb | None,
) -> Morphism:
    if not morphism.lanes:
        return morphism

    if isinstance(target_duration_cycles, Expr):
        raise TypeError("Parallel padding requires a concrete target duration.")
    padding_cycles = target_duration_cycles - morphism.total_duration_cycles
    if padding_cycles <= 0:
        return morphism

    new_lanes = {}
    for channel, lane in morphism.lanes.items():
        end_state = lane.effective_end_state if lane.effective_end_state is not None else lane.initial_state
        padding_trace = (auto_breadcrumb,) + (
            (compose_breadcrumb,) if compose_breadcrumb is not None else ()
        )
        padding_op = AtomicMorphism(
            channel=channel,
            start_state=end_state,
            end_state=end_state,
            duration_cycles=padding_cycles,
            operation_type=OperationType.IDENTITY,
            timing_kind=TimingKind.DELAY,
            debug_trace=padding_trace,
        )
        new_lanes[channel] = Lane(lane.operations + (padding_op,))
    return Morphism(new_lanes)
