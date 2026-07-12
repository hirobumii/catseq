"""Structure-preserving Morphism composition over append-only arenas."""

from __future__ import annotations

from ..debug import auto_generated_breadcrumb
from ..expr import Expr, structurally_equal
from ..types.common import (
    AtomicMorphism,
    Channel,
    DebugBreadcrumb,
    OperationType,
    State,
    TimingKind,
)
from ..types.ttl import TTLState
from .core import (
    Morphism,
    _LaneRef,
    _concatenate_lane_duration,
    _unresolved_lane_refs,
)


def _max_duration(left: int | Expr, right: int | Expr) -> int | Expr:
    if structurally_equal(left, right):
        return left
    if isinstance(left, Expr) or isinstance(right, Expr):
        return Expr.maximum(left, right)
    return max(left, right)


def _combine_refs(
    arena,
    left: _LaneRef,
    right: _LaneRef,
    *,
    strict: bool,
    right_breadcrumb: DebugBreadcrumb | None,
) -> _LaneRef:
    if left.root is None:
        return right
    if right.root is None:
        return left
    root = arena.serial(
        left.root,
        right.root,
        strict=strict,
        right_breadcrumb=right_breadcrumb,
    )
    return _LaneRef(
        root=root,
        duration=_concatenate_lane_duration(arena, left.duration, right),
        initial_state=left.initial_state,
        end_state=right.end_state,
        effective_start_state=(
            left.effective_start_state
            if left.has_effective
            else right.effective_start_state
        ),
        effective_end_state=(
            right.effective_end_state
            if right.has_effective
            else left.effective_end_state
        ),
        has_effective=left.has_effective or right.has_effective,
    )


def _identity_ref(
    morphism: Morphism,
    channel: Channel,
    state: State | None,
    duration: int | Expr,
    *,
    breadcrumb: DebugBreadcrumb | None = None,
    reason: str,
) -> _LaneRef:
    trace: tuple[DebugBreadcrumb, ...] = (auto_generated_breadcrumb(reason),)
    if breadcrumb is not None:
        trace += (breadcrumb,)
    operation = AtomicMorphism(
        channel=channel,
        start_state=state,
        end_state=state,
        duration_cycles=duration,
        operation_type=OperationType.IDENTITY,
        timing_kind=TimingKind.DELAY,
        debug_trace=trace,
    )
    return _LaneRef(
        root=morphism._arena.atomic(operation),
        duration=duration,
        initial_state=state,
        end_state=state,
        effective_start_state=state,
        effective_end_state=state,
        has_effective=False,
    )


def strict_compose_morphisms(
    first: Morphism,
    second: Morphism,
    *,
    lhs_breadcrumb: DebugBreadcrumb | None = None,
    rhs_breadcrumb: DebugBreadcrumb | None = None,
) -> Morphism:
    """Record strict serial composition; state continuity is a compiler pass."""
    second_root, second_refs = second._import_into(first._arena)
    root = first._arena.serial(
        first._root,
        second_root,
        strict=True,
        right_breadcrumb=rhs_breadcrumb,
    )
    if not first._summaries_resolved or not second._summaries_resolved:
        return Morphism._from_parts(
            first._arena,
            root,
            _unresolved_lane_refs(
                first._lane_refs.keys() | second_refs.keys()
            ),
            -1,
            summaries_resolved=False,
        )
    result_refs: dict[Channel, _LaneRef] = {}
    for channel in first._lane_refs.keys() | second_refs.keys():
        left = first._lane_refs.get(channel)
        right = second_refs.get(channel)
        if left is None and right is not None:
            left = _identity_ref(
                first,
                channel,
                right.effective_start_state,
                first.total_duration_expr,
                breadcrumb=lhs_breadcrumb,
                reason="strict_compose_missing_lhs_channel",
            )
        if right is None and left is not None:
            right = _identity_ref(
                first,
                channel,
                left.effective_end_state,
                second.total_duration_expr,
                reason="strict_compose_missing_rhs_channel",
            )
        if left is None or right is None:
            raise AssertionError("Strict composition lost a channel")
        result_refs[channel] = _combine_refs(
            first._arena,
            left,
            right,
            strict=True,
            right_breadcrumb=rhs_breadcrumb,
        )
    result_duration = (
        next(iter(result_refs.values())).duration
        if result_refs
        else first.total_duration_expr + second.total_duration_expr
    )
    return Morphism._from_parts(
        first._arena,
        root,
        result_refs,
        result_duration,
    )


def auto_compose_morphisms(
    first: Morphism,
    second: Morphism,
    *,
    lhs_breadcrumb: DebugBreadcrumb | None = None,
    rhs_breadcrumb: DebugBreadcrumb | None = None,
) -> Morphism:
    """Record automatic serial composition and update channel summaries."""
    if (
        second._summaries_resolved
        and not second._lane_refs
        and structurally_equal(second.total_duration_expr, 0)
    ):
        return first
    second_root, second_refs = second._import_into(first._arena)

    if not first._summaries_resolved or not second._summaries_resolved:
        root = first._arena.serial(
            first._root,
            second_root,
            right_breadcrumb=rhs_breadcrumb,
        )
        return Morphism._from_parts(
            first._arena,
            root,
            _unresolved_lane_refs(
                first._lane_refs.keys() | second_refs.keys()
            ),
            -1,
            summaries_resolved=False,
        )

    if not first._lane_refs and not second_refs:
        duration = _max_duration(
            first.total_duration_expr,
            second.total_duration_expr,
        )
        root = first._arena.parallel(first._root, second_root)
        return Morphism._from_parts(first._arena, root, {}, duration)

    root = first._arena.serial(
        first._root,
        second_root,
        right_breadcrumb=rhs_breadcrumb,
    )
    result_refs: dict[Channel, _LaneRef] = {}
    for channel in first._lane_refs.keys() | second_refs.keys():
        left = first._lane_refs.get(channel)
        right = second_refs.get(channel)
        if left is None and right is not None:
            left = _identity_ref(
                first,
                channel,
                right.effective_start_state,
                first.total_duration_expr,
                breadcrumb=lhs_breadcrumb,
                reason="auto_compose_missing_lhs_channel",
            )
        if right is None and left is not None:
            right = _identity_ref(
                first,
                channel,
                left.effective_end_state,
                second.total_duration_expr,
                reason="auto_compose_missing_rhs_channel",
            )
        if left is None or right is None:
            raise AssertionError("Automatic composition lost a channel")

        if not right.has_effective:
            inferred_state = left.effective_end_state
            if inferred_state is None:
                inferred_state = left.initial_state
            if inferred_state is None:
                inferred_state = TTLState.OFF
            if (
                right.initial_state != inferred_state
                or right.end_state != inferred_state
            ):
                right = _identity_ref(
                    first,
                    channel,
                    inferred_state,
                    right.duration,
                    reason="auto_identity_state_inference",
                )

        result_refs[channel] = _combine_refs(
            first._arena,
            left,
            right,
            strict=False,
            right_breadcrumb=rhs_breadcrumb,
        )

    result_duration = next(iter(result_refs.values())).duration
    return Morphism._from_parts(
        first._arena,
        root,
        result_refs,
        result_duration,
    )


def parallel_compose_morphisms(
    left: Morphism,
    right: Morphism,
    *,
    lhs_breadcrumb: DebugBreadcrumb | None = None,
    rhs_breadcrumb: DebugBreadcrumb | None = None,
) -> Morphism:
    """Record parallel composition and pad only the compatibility lane summary."""
    overlapping = left._lane_refs.keys() & right._lane_refs.keys()
    if overlapping:
        names = [channel.global_id for channel in overlapping]
        raise ValueError(f"Cannot compose: overlapping channels {names}")
    right_root, right_refs = right._import_into(left._arena)
    root = left._arena.parallel(
        left._root,
        right_root,
        right_breadcrumb=rhs_breadcrumb,
    )
    if not left._summaries_resolved or not right._summaries_resolved:
        return Morphism._from_parts(
            left._arena,
            root,
            _unresolved_lane_refs(
                left._lane_refs.keys() | right_refs.keys()
            ),
            -1,
            summaries_resolved=False,
        )
    duration = _max_duration(left.total_duration_expr, right.total_duration_expr)
    left_refs = dict(left._lane_refs)

    if not structurally_equal(left.total_duration_expr, duration):
        padding = duration - left.total_duration_expr
        for channel, lane_ref in tuple(left_refs.items()):
            identity = _identity_ref(
                left,
                channel,
                lane_ref.effective_end_state,
                padding,
                breadcrumb=lhs_breadcrumb,
                reason="parallel_padding",
            )
            left_refs[channel] = _combine_refs(
                left._arena,
                lane_ref,
                identity,
                strict=False,
                right_breadcrumb=None,
            )

    if not structurally_equal(right.total_duration_expr, duration):
        padding = duration - right.total_duration_expr
        for channel, lane_ref in tuple(right_refs.items()):
            identity = _identity_ref(
                left,
                channel,
                lane_ref.effective_end_state,
                padding,
                breadcrumb=rhs_breadcrumb,
                reason="parallel_padding",
            )
            right_refs[channel] = _combine_refs(
                left._arena,
                lane_ref,
                identity,
                strict=False,
                right_breadcrumb=None,
            )

    return Morphism._from_parts(
        left._arena,
        root,
        {**left_refs, **right_refs},
        duration,
    )
