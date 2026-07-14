"""PROTOTYPE ONLY: runtime replacement of Morphism with an arena-backed DAG.

The public composition operators remain unchanged. Legacy Lane materialization
is retained only as a compatibility view for existing CatSeq/RB1 code that reads
``morphism.lanes`` during construction.
"""

from __future__ import annotations

from array import array
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import sys
from typing import Iterator

from catseq.debug import (
    annotate_atomic,
    auto_generated_breadcrumb,
    capture_callsite as legacy_capture_callsite,
    compose_breadcrumb,
    next_compose_id,
)
from catseq.expr import Expr, structurally_equal
from catseq.expr.realize import _realize_atomic
from catseq.lanes import Lane as LegacyLane
from catseq.morphism.compose import (
    auto_compose_morphisms as legacy_auto_compose,
    parallel_compose_morphisms as legacy_parallel_compose,
    strict_compose_morphisms as legacy_strict_compose,
)
from catseq.morphism.core import Morphism as LegacyMorphism
from catseq.morphism.core import from_atomic as legacy_from_atomic
from catseq.time_utils import cycles_to_time, us
from catseq.types.common import AtomicMorphism, Channel, OperationType, TimingKind
from catseq.types.rwg import RWGUninitialized


LEAF = 0
AUTO = 1
STRICT = 2
PARALLEL = 3
CONCAT = 4
ATOMIC_LEAF = 5
DEFERRED_CHANNEL = 6
DEFERRED_APPLY = 7
DEFERRED_BATCH = 8
REPEAT = 9

_ACTIVE_ARENA: ContextVar["MorphismArena | None"] = ContextVar(
    "prototype_morphism_arena", default=None
)
_CALLSITE_CACHE: dict[tuple[object, int, int], object] = {}


def _cached_capture_callsite(stacklevel: int = 0):
    try:
        target = sys._getframe(stacklevel + 1)
    except ValueError:
        return None
    try:
        key = (target.f_code, target.f_lineno, stacklevel)
        if key not in _CALLSITE_CACHE:
            _CALLSITE_CACHE[key] = legacy_capture_callsite(stacklevel + 1)
        return _CALLSITE_CACHE[key]
    finally:
        del target


@dataclass(frozen=True, slots=True)
class NodeSummary:
    channel_mask: int
    duration: int | Expr | None


@dataclass(frozen=True, slots=True)
class ChannelStateSummary:
    initial_state: object | None
    end_state: object | None
    effective_start_state: object | None
    effective_end_state: object | None
    has_effective_operation: bool


class MorphismArena:
    __slots__ = (
        "cache",
        "cache_hits",
        "binding_env",
        "channel_ids",
        "channel_masks",
        "channels_by_id",
        "children_evaluated",
        "kinds",
        "left",
        "materialize_requests",
        "payload",
        "right",
        "state_cache",
        "state_query_hits",
        "state_query_nodes",
        "state_query_requests",
        "summaries",
    )

    def __init__(self) -> None:
        self.kinds = array("b")
        self.left = array("i")
        self.right = array("i")
        self.payload: list[object] = []
        self.summaries: list[NodeSummary] = []
        self.cache: dict[int, LegacyMorphism] = {}
        self.binding_env: dict[str, object] | None = None
        self.channel_ids: dict[int, int] = {}
        self.channels_by_id: list[object] = []
        self.channel_masks: dict[int, tuple[object, ...]] = {}
        self.state_cache: list[dict[int, ChannelStateSummary | None]] = []
        self.materialize_requests = 0
        self.cache_hits = 0
        self.children_evaluated = 0
        self.state_query_requests = 0
        self.state_query_hits = 0
        self.state_query_nodes = 0

    def fork(self, bindings: Mapping[str, object]) -> "MorphismArena":
        """Copy compact topology while sharing immutable node payloads."""

        target = MorphismArena()
        target.kinds = array("b", self.kinds)
        target.left = array("i", self.left)
        target.right = array("i", self.right)
        target.payload = list(self.payload)
        target.summaries = list(self.summaries)
        target.channel_ids = dict(self.channel_ids)
        target.channels_by_id = list(self.channels_by_id)
        target.channel_masks = dict(self.channel_masks)
        target.state_cache = [{} for _ in self.state_cache]
        target.binding_env = dict(bindings)
        return target

    def add_leaf(self, value: LegacyMorphism) -> int:
        channel_mask = 0
        for channel in value.lanes:
            channel_mask |= 1 << self.channel_id(channel)
        node_id = len(self.kinds)
        self.kinds.append(LEAF)
        self.left.append(-1)
        self.right.append(-1)
        self.payload.append(value)
        self.summaries.append(NodeSummary(channel_mask, value.total_duration_expr))
        self.state_cache.append({})
        return node_id

    def add_atomic(self, operation: AtomicMorphism) -> int:
        channel = operation.channel
        if channel is None:
            raise ValueError(
                "Cannot create Morphism from an AtomicMorphism without a channel."
            )
        channel_mask = 1 << self.channel_id(channel)
        node_id = len(self.kinds)
        self.kinds.append(ATOMIC_LEAF)
        self.left.append(-1)
        self.right.append(-1)
        self.payload.append(operation)
        self.summaries.append(NodeSummary(channel_mask, operation.duration_cycles))
        self.state_cache.append({})
        return node_id

    def add_deferred_channel(
        self,
        definition: object,
        channel: object,
        start_state: object | None,
    ) -> int:
        node_id = len(self.kinds)
        self.kinds.append(DEFERRED_CHANNEL)
        self.left.append(-1)
        self.right.append(-1)
        self.payload.append((definition, channel, start_state))
        self.summaries.append(
            NodeSummary(1 << self.channel_id(channel), None)
        )
        self.state_cache.append({})
        return node_id

    def add_deferred_apply(
        self,
        base: int,
        operations: object,
        application_breadcrumbs: object,
    ) -> int:
        node_id = len(self.kinds)
        self.kinds.append(DEFERRED_APPLY)
        self.left.append(base)
        self.right.append(-1)
        self.payload.append(
            (
                dict(operations),
                None
                if application_breadcrumbs is None
                else dict(application_breadcrumbs),
            )
        )
        self.summaries.append(
            NodeSummary(self.summaries[base].channel_mask, None)
        )
        self.state_cache.append({})
        return node_id

    def add_deferred_batch(
        self,
        state_source: int,
        operations: object,
    ) -> int:
        channel_mask = 0
        for channel in operations:
            channel_mask |= 1 << self.channel_id(channel)
        node_id = len(self.kinds)
        self.kinds.append(DEFERRED_BATCH)
        self.left.append(state_source)
        self.right.append(-1)
        self.payload.append(dict(operations))
        self.summaries.append(NodeSummary(channel_mask, None))
        self.state_cache.append({})
        return node_id

    def add_repeat(
        self,
        child: int,
        count: int,
        assembler_sequence: object,
    ) -> int:
        node_id = len(self.kinds)
        self.kinds.append(REPEAT)
        self.left.append(child)
        self.right.append(-1)
        self.payload.append((count, assembler_sequence))
        self.summaries.append(
            NodeSummary(self.summaries[child].channel_mask, None)
        )
        self.state_cache.append({})
        return node_id

    def add_binary(self, kind: int, left: int, right: int) -> int:
        left_summary = self.summaries[left]
        right_summary = self.summaries[right]
        channel_mask = left_summary.channel_mask | right_summary.channel_mask
        if kind == PARALLEL:
            overlap = left_summary.channel_mask & right_summary.channel_mask
            if overlap:
                raise ValueError(
                    f"Cannot compose: overlapping channels {self.channels(overlap)}"
                )
            duration = (
                None
                if left_summary.duration is None or right_summary.duration is None
                else _max_duration(left_summary.duration, right_summary.duration)
            )
        elif kind == AUTO and not right_summary.channel_mask:
            if right_summary.duration is None:
                duration = None
            elif structurally_equal(right_summary.duration, 0):
                duration = left_summary.duration
            elif not left_summary.channel_mask:
                duration = (
                    None
                    if left_summary.duration is None
                    else _max_duration(
                        left_summary.duration,
                        right_summary.duration,
                    )
                )
            else:
                duration = (
                    None
                    if left_summary.duration is None
                    else left_summary.duration + right_summary.duration
                )
        else:
            duration = (
                None
                if left_summary.duration is None or right_summary.duration is None
                else left_summary.duration + right_summary.duration
            )

        node_id = len(self.kinds)
        self.kinds.append(kind)
        self.left.append(left)
        self.right.append(right)
        self.payload.append(None)
        self.summaries.append(NodeSummary(channel_mask, duration))
        self.state_cache.append({})
        return node_id

    def channel_id(self, channel: object) -> int:
        object_id = id(channel)
        channel_id = self.channel_ids.get(object_id)
        if channel_id is not None:
            return channel_id
        channel_id = len(self.channels_by_id)
        self.channel_ids[object_id] = channel_id
        self.channels_by_id.append(channel)
        return channel_id

    def channels(self, mask: int) -> tuple[object, ...]:
        cached = self.channel_masks.get(mask)
        if cached is not None:
            return cached
        channels: list[object] = []
        remaining = mask
        while remaining:
            lowest = remaining & -remaining
            channels.append(self.channels_by_id[lowest.bit_length() - 1])
            remaining ^= lowest
        result = tuple(channels)
        self.channel_masks[mask] = result
        return result

    def materialize(self, root: int) -> LegacyMorphism:
        self.materialize_requests += 1
        if self.kinds[root] == LEAF:
            value = self.payload[root]
            if not isinstance(value, LegacyMorphism):
                raise AssertionError("leaf without Morphism payload")
            return _resolve_legacy_bindings(value, self.binding_env)
        if self.kinds[root] == ATOMIC_LEAF:
            cached_atomic = self.cache.get(root)
            if cached_atomic is not None:
                self.cache_hits += 1
                return cached_atomic
            value = _materialize_atomic(
                self.payload[root],
                self.binding_env,
            )
            self.cache[root] = value
            return value
        if self.kinds[root] == DEFERRED_CHANNEL:
            cached_deferred = self.cache.get(root)
            if cached_deferred is not None:
                self.cache_hits += 1
                return cached_deferred
            value = _materialize_deferred_channel(self, self.payload[root])
            self.cache[root] = value
            return value
        cached = self.cache.get(root)
        if cached is not None:
            self.cache_hits += 1
            return cached

        reachable: set[int] = set()
        uses: dict[int, int] = {}
        stack = [root]
        while stack:
            node_id = stack.pop()
            if node_id in reachable or node_id in self.cache:
                continue
            reachable.add(node_id)
            if self.kinds[node_id] in {
                LEAF,
                ATOMIC_LEAF,
                DEFERRED_CHANNEL,
            }:
                continue
            children = (
                (self.left[node_id],)
                if self.kinds[node_id]
                in {DEFERRED_APPLY, DEFERRED_BATCH, REPEAT}
                else (self.left[node_id], self.right[node_id])
            )
            for child in children:
                uses[child] = uses.get(child, 0) + 1
                stack.append(child)

        values: dict[int, LegacyMorphism] = {}
        for node_id in sorted(reachable):
            kind = self.kinds[node_id]
            if kind == LEAF:
                value = self.payload[node_id]
                if value is None:
                    raise AssertionError("leaf without payload")
                value = _resolve_legacy_bindings(value, self.binding_env)
            elif kind == ATOMIC_LEAF:
                value = _materialize_atomic(
                    self.payload[node_id],
                    self.binding_env,
                )
            elif kind == DEFERRED_CHANNEL:
                value = _materialize_deferred_channel(
                    self,
                    self.payload[node_id],
                )
            elif kind == DEFERRED_APPLY:
                child_id = self.left[node_id]
                child = self.cache.get(child_id) or values[child_id]
                value = _materialize_deferred_apply(
                    self,
                    child,
                    self.payload[node_id],
                )
                self.children_evaluated += 1
                remaining = uses[child_id] - 1
                uses[child_id] = remaining
                if remaining == 0 and child_id not in self.cache:
                    values.pop(child_id, None)
            elif kind == DEFERRED_BATCH:
                child_id = self.left[node_id]
                child = self.cache.get(child_id) or values[child_id]
                value = _materialize_deferred_batch(
                    self,
                    child,
                    self.payload[node_id],
                )
                self.children_evaluated += 1
                remaining = uses[child_id] - 1
                uses[child_id] = remaining
                if remaining == 0 and child_id not in self.cache:
                    values.pop(child_id, None)
            elif kind == REPEAT:
                child_id = self.left[node_id]
                child = self.cache.get(child_id) or values[child_id]
                value = _materialize_repeat(
                    self,
                    child,
                    self.payload[node_id],
                )
                self.children_evaluated += 1
                remaining = uses[child_id] - 1
                uses[child_id] = remaining
                if remaining == 0 and child_id not in self.cache:
                    values.pop(child_id, None)
            else:
                left_id = self.left[node_id]
                right_id = self.right[node_id]
                left = self.cache.get(left_id) or values[left_id]
                right = self.cache.get(right_id) or values[right_id]
                try:
                    value = _combine_legacy(
                        kind,
                        left,
                        right,
                        self.payload[node_id],
                    )
                except (TypeError, ValueError) as error:
                    context = _format_node_error_context(self, node_id)
                    raise type(error)(f"{error}\n{context}") from error
                self.children_evaluated += 1
                for child in (left_id, right_id):
                    remaining = uses[child] - 1
                    uses[child] = remaining
                    if remaining == 0 and child not in self.cache:
                        values.pop(child, None)
            values[node_id] = value

        result = values[root]
        self.cache[root] = result
        return result

    def query_state(
        self, root: int, channel: object
    ) -> ChannelStateSummary | None:
        self.state_query_requests += 1
        channel_id = self.channel_ids.get(id(channel))
        if channel_id is None:
            return None
        root_cache = self.state_cache[root]
        if channel_id in root_cache:
            self.state_query_hits += 1
            return root_cache[channel_id]
        channel_bit = 1 << channel_id
        if not self.summaries[root].channel_mask & channel_bit:
            root_cache[channel_id] = None
            return None

        reachable: set[int] = set()
        stack = [root]
        while stack:
            node_id = stack.pop()
            if channel_id in self.state_cache[node_id] or node_id in reachable:
                continue
            reachable.add(node_id)
            if self.kinds[node_id] in {
                LEAF,
                ATOMIC_LEAF,
                DEFERRED_CHANNEL,
                DEFERRED_APPLY,
                DEFERRED_BATCH,
                REPEAT,
            }:
                continue
            for child in (self.left[node_id], self.right[node_id]):
                if self.summaries[child].channel_mask & channel_bit:
                    stack.append(child)

        for node_id in sorted(reachable):
            kind = self.kinds[node_id]
            if kind == LEAF:
                value = self.payload[node_id]
                if not isinstance(value, LegacyMorphism):
                    raise AssertionError("leaf without Morphism payload")
                lane = value.lanes.get(self.channels_by_id[channel_id])
                state = _summarize_lane(lane) if lane is not None else None
            elif kind == ATOMIC_LEAF:
                operation = self.payload[node_id]
                if not isinstance(operation, AtomicMorphism):
                    raise AssertionError("atomic leaf without AtomicMorphism payload")
                state = _summarize_atomic(operation)
            elif kind in {
                DEFERRED_CHANNEL,
                DEFERRED_APPLY,
                DEFERRED_BATCH,
                REPEAT,
            }:
                value = self.materialize(node_id)
                lane = value.lanes.get(self.channels_by_id[channel_id])
                state = _summarize_lane(lane) if lane is not None else None
            else:
                left_id = self.left[node_id]
                right_id = self.right[node_id]
                left_state = self.state_cache[left_id].get(channel_id)
                right_state = self.state_cache[right_id].get(channel_id)
                state = _combine_states(kind, left_state, right_state)
            self.state_cache[node_id][channel_id] = state
            self.state_query_nodes += 1
        return root_cache[channel_id]

    def stats(self) -> dict[str, int]:
        return {
            "node_count": len(self.kinds),
            "leaf_nodes": self.kinds.count(LEAF),
            "atomic_leaf_nodes": self.kinds.count(ATOMIC_LEAF),
            "deferred_channel_nodes": self.kinds.count(DEFERRED_CHANNEL),
            "deferred_apply_nodes": self.kinds.count(DEFERRED_APPLY),
            "deferred_batch_nodes": self.kinds.count(DEFERRED_BATCH),
            "repeat_nodes": self.kinds.count(REPEAT),
            "auto_nodes": self.kinds.count(AUTO),
            "strict_nodes": self.kinds.count(STRICT),
            "parallel_nodes": self.kinds.count(PARALLEL),
            "concat_nodes": self.kinds.count(CONCAT),
            "cached_roots": len(self.cache),
            "materialize_requests": self.materialize_requests,
            "materialize_cache_hits": self.cache_hits,
            "materialized_composition_nodes": self.children_evaluated,
            "state_query_requests": self.state_query_requests,
            "state_query_hits": self.state_query_hits,
            "state_query_nodes": self.state_query_nodes,
            "cached_state_queries": sum(len(cache) for cache in self.state_cache),
            "channel_count": len(self.channels_by_id),
        }


def _summarize_lane(lane: LegacyLane) -> ChannelStateSummary:
    has_effective = any(
        operation.operation_type != OperationType.IDENTITY
        for operation in lane.operations
    )
    return ChannelStateSummary(
        initial_state=lane.initial_state,
        end_state=lane.end_state,
        effective_start_state=lane.effective_start_state,
        effective_end_state=lane.effective_end_state,
        has_effective_operation=has_effective,
    )


def _summarize_atomic(operation: AtomicMorphism) -> ChannelStateSummary:
    return ChannelStateSummary(
        initial_state=operation.start_state,
        end_state=operation.end_state,
        effective_start_state=operation.start_state,
        effective_end_state=operation.end_state,
        has_effective_operation=operation.operation_type != OperationType.IDENTITY,
    )


def _materialize_atomic(
    payload: object,
    bindings: Mapping[str, object] | None,
) -> LegacyMorphism:
    if not isinstance(payload, AtomicMorphism) or payload.channel is None:
        raise AssertionError("atomic leaf without a channel-bound operation")
    operation = payload if bindings is None else _realize_atomic(payload, bindings)
    return LegacyMorphism({payload.channel: LegacyLane((operation,))})


def _resolve_legacy_bindings(
    morphism: LegacyMorphism,
    bindings: Mapping[str, object] | None,
) -> LegacyMorphism:
    if bindings is None:
        return morphism
    return LegacyMorphism(
        {
            channel: LegacyLane(
                tuple(
                    _realize_atomic(operation, bindings)
                    if isinstance(operation, AtomicMorphism)
                    else operation
                    for operation in lane.operations
                )
            )
            for channel, lane in morphism.lanes.items()
        },
        _duration_cycles=(
            morphism._duration_cycles.resolve(None, bindings)
            if isinstance(morphism._duration_cycles, Expr)
            else morphism._duration_cycles
        ),
    )


def _execute_deferred_definition(
    arena: MorphismArena,
    definition: object,
    channel: object,
    start_state: object | None,
) -> LegacyMorphism:
    if _ORIGINAL_MORPHISM_DEF_CALL is None:
        raise AssertionError("arena runtime was not installed")
    token = _ACTIVE_ARENA.set(arena)
    try:
        result = _ORIGINAL_MORPHISM_DEF_CALL(
            definition,
            channel,
            start_state,
        )
        if isinstance(result, ArenaMorphism):
            return result._legacy()
        if isinstance(result, LegacyMorphism):
            return result
        raise TypeError(f"deferred definition returned {type(result)}")
    finally:
        _ACTIVE_ARENA.reset(token)


def _materialize_deferred_channel(
    arena: MorphismArena,
    payload: object,
) -> LegacyMorphism:
    if not isinstance(payload, tuple) or len(payload) != 3:
        raise AssertionError("invalid deferred-channel payload")
    definition, channel, start_state = payload
    return _execute_deferred_definition(
        arena,
        definition,
        channel,
        start_state,
    )


def _materialize_deferred_apply(
    arena: MorphismArena,
    base: LegacyMorphism,
    payload: object,
) -> LegacyMorphism:
    if not isinstance(payload, tuple) or len(payload) != 2:
        raise AssertionError("invalid deferred-apply payload")
    operations, application_breadcrumbs = payload
    if not isinstance(operations, dict):
        raise AssertionError("deferred operations were not snapshotted")

    operation_results = {}
    max_duration: int | Expr = 0
    for channel, definition in operations.items():
        lane = base.lanes[channel]
        start_state = lane.effective_end_state or RWGUninitialized()
        result = _execute_deferred_definition(
            arena,
            definition,
            channel,
            start_state,
        )
        if isinstance(application_breadcrumbs, dict):
            result = _legacy_annotate(
                result,
                application_breadcrumbs.get(channel, ()),
            )
        operation_results[channel] = result
        duration = result.total_duration_expr
        if isinstance(duration, Expr):
            if not structurally_equal(max_duration, 0) and not structurally_equal(
                max_duration,
                duration,
            ):
                raise TypeError("prototype deferred durations differ symbolically")
            max_duration = duration
        else:
            if isinstance(max_duration, Expr):
                raise TypeError("prototype deferred durations mix symbolic and concrete")
            max_duration = max(max_duration, duration)

    aligned = {}
    for channel, result in operation_results.items():
        current_duration = result.total_duration_expr
        if structurally_equal(current_duration, max_duration):
            aligned[channel] = result
            continue
        if isinstance(current_duration, Expr) or isinstance(max_duration, Expr):
            raise TypeError("prototype deferred padding is symbolic")
        result_lane = result.lanes.get(channel, LegacyLane(()))
        end_state = result_lane.effective_end_state or RWGUninitialized()
        application_trace = (
            application_breadcrumbs.get(channel, ())
            if isinstance(application_breadcrumbs, dict)
            else ()
        )
        padding = AtomicMorphism(
            channel=channel,
            start_state=end_state,
            end_state=end_state,
            duration_cycles=max_duration - current_duration,
            operation_type=OperationType.IDENTITY,
            timing_kind=TimingKind.DELAY,
            debug_trace=(auto_generated_breadcrumb("deferred_padding"),)
            + application_trace,
        )
        aligned[channel] = LegacyMorphism(
            {channel: LegacyLane(result_lane.operations + (padding,))}
        )

    suffix_lanes = {}
    for channel, lane in base.lanes.items():
        if channel in aligned:
            suffix_lanes[channel] = aligned[channel].lanes[channel]
            continue
        state = lane.effective_end_state
        wait = AtomicMorphism(
            channel=channel,
            start_state=state,
            end_state=state,
            duration_cycles=max_duration,
            operation_type=OperationType.IDENTITY,
            timing_kind=TimingKind.DELAY,
            debug_trace=(
                auto_generated_breadcrumb("prototype_deferred_idle_alignment"),
            ),
        )
        suffix_lanes[channel] = LegacyLane((wait,))
    return _concat_legacy(base, LegacyMorphism(suffix_lanes))


def _materialize_deferred_batch(
    arena: MorphismArena,
    state_source: LegacyMorphism,
    payload: object,
) -> LegacyMorphism:
    if not isinstance(payload, dict):
        raise AssertionError("invalid deferred-batch payload")
    result = None
    for channel, definition in payload.items():
        lane = state_source.lanes[channel]
        start_state = lane.effective_end_state or RWGUninitialized()
        channel_result = _execute_deferred_definition(
            arena,
            definition,
            channel,
            start_state,
        )
        result = (
            channel_result
            if result is None
            else legacy_parallel_compose(result, channel_result)
        )
    return result or LegacyMorphism({}, _duration_cycles=0)


def _materialize_repeat(
    arena: MorphismArena,
    child: LegacyMorphism,
    payload: object,
) -> LegacyMorphism:
    if _ORIGINAL_REPEAT_MORPHISM is None:
        raise AssertionError("repeat runtime was not installed")
    if not isinstance(payload, tuple) or len(payload) != 2:
        raise AssertionError("invalid repeat payload")
    count, assembler_sequence = payload
    token = _ACTIVE_ARENA.set(arena)
    try:
        result = _ORIGINAL_REPEAT_MORPHISM(
            child,
            count,
            assembler_sequence,
        )
        if isinstance(result, ArenaMorphism):
            return result._legacy()
        if isinstance(result, LegacyMorphism):
            return result
        raise TypeError(f"repeat_morphism returned {type(result)}")
    finally:
        _ACTIVE_ARENA.reset(token)


def _combine_states(
    kind: int,
    left: ChannelStateSummary | None,
    right: ChannelStateSummary | None,
) -> ChannelStateSummary | None:
    if kind == PARALLEL:
        return left if left is not None else right
    if left is None:
        return right
    if right is None:
        end_state = (
            left.effective_end_state
            if kind in {AUTO, STRICT}
            else left.end_state
        )
        return ChannelStateSummary(
            initial_state=left.initial_state,
            end_state=end_state,
            effective_start_state=left.effective_start_state,
            effective_end_state=left.effective_end_state,
            has_effective_operation=left.has_effective_operation,
        )

    has_effective = (
        left.has_effective_operation or right.has_effective_operation
    )
    effective_start = (
        left.effective_start_state
        if left.has_effective_operation
        else right.effective_start_state
    )
    effective_end = (
        right.effective_end_state
        if right.has_effective_operation
        else left.effective_end_state
    )
    if kind == AUTO and not right.has_effective_operation:
        end_state = left.effective_end_state
    else:
        end_state = right.end_state
    return ChannelStateSummary(
        initial_state=left.initial_state,
        end_state=end_state,
        effective_start_state=effective_start,
        effective_end_state=effective_end,
        has_effective_operation=has_effective,
    )


def _max_duration(left: int | Expr, right: int | Expr) -> int | Expr:
    if structurally_equal(left, right):
        return left
    if isinstance(left, Expr) or isinstance(right, Expr):
        raise TypeError("prototype does not support unequal symbolic parallel durations")
    return max(left, right)


def _format_node_error_context(arena: MorphismArena, node_id: int) -> str:
    kind_names = {
        AUTO: "auto-serial",
        STRICT: "strict-serial",
        PARALLEL: "parallel",
        CONCAT: "deferred-concat",
    }
    details = [
        f"Arena node {node_id} ({kind_names.get(arena.kinds[node_id], 'unknown')}, "
        f"left={arena.left[node_id]}, right={arena.right[node_id]})"
    ]
    payload = arena.payload[node_id]
    if isinstance(payload, tuple):
        for side, breadcrumb in zip(("lhs", "rhs"), payload):
            frame = getattr(breadcrumb, "frame", None)
            if frame is not None:
                details.append(f"{side}: {frame.describe()}")
    return "; ".join(details)


def _legacy_annotate(
    morphism: LegacyMorphism,
    breadcrumbs,
) -> LegacyMorphism:
    if not breadcrumbs or not morphism.lanes:
        return morphism
    return LegacyMorphism(
        {
            channel: LegacyLane(
                tuple(annotate_atomic(operation, breadcrumbs) for operation in lane.operations)
            )
            for channel, lane in morphism.lanes.items()
        }
    )


def _legacy_auto_full(
    left: LegacyMorphism,
    right: LegacyMorphism,
    lhs_breadcrumb=None,
    rhs_breadcrumb=None,
) -> LegacyMorphism:
    if not right.lanes:
        if structurally_equal(right.total_duration_expr, 0):
            return left
        if not left.lanes:
            return LegacyMorphism(
                lanes={},
                _duration_cycles=_max_duration(
                    left.total_duration_expr, right.total_duration_expr
                ),
            )
        new_lanes = {}
        for channel, lane in left.lanes.items():
            inferred_state = lane.effective_end_state
            if inferred_state is None and lane.initial_state is not None:
                inferred_state = lane.initial_state
            wait = AtomicMorphism(
                channel=channel,
                start_state=inferred_state,
                end_state=inferred_state,
                duration_cycles=right.total_duration_expr,
                operation_type=OperationType.IDENTITY,
                timing_kind=TimingKind.DELAY,
                debug_trace=(
                    auto_generated_breadcrumb("prototype_channelless_identity"),
                )
                + ((rhs_breadcrumb,) if rhs_breadcrumb is not None else ()),
            )
            new_lanes[channel] = LegacyLane(lane.operations + (wait,))
        return LegacyMorphism(new_lanes)
    return legacy_auto_compose(
        left,
        right,
        lhs_breadcrumb=lhs_breadcrumb,
        rhs_breadcrumb=rhs_breadcrumb,
    )


def _concat_legacy(left: LegacyMorphism, right: LegacyMorphism) -> LegacyMorphism:
    lanes = {}
    for channel in set(left.lanes) | set(right.lanes):
        left_ops = left.lanes.get(channel, LegacyLane(())).operations
        right_ops = right.lanes.get(channel, LegacyLane(())).operations
        lanes[channel] = LegacyLane(left_ops + right_ops)
    if not lanes:
        return LegacyMorphism(
            lanes={},
            _duration_cycles=left.total_duration_expr + right.total_duration_expr,
        )
    return LegacyMorphism(lanes)


def _combine_legacy(
    kind: int,
    left: LegacyMorphism,
    right: LegacyMorphism,
    payload: object,
) -> LegacyMorphism:
    lhs_breadcrumb = None
    rhs_breadcrumb = None
    if isinstance(payload, tuple):
        lhs_breadcrumb, rhs_breadcrumb = payload
    if kind == AUTO:
        return _legacy_auto_full(
            left,
            right,
            lhs_breadcrumb=lhs_breadcrumb,
            rhs_breadcrumb=rhs_breadcrumb,
        )
    if kind == STRICT:
        return legacy_strict_compose(
            left,
            right,
            lhs_breadcrumb=lhs_breadcrumb,
            rhs_breadcrumb=rhs_breadcrumb,
        )
    if kind == PARALLEL:
        return legacy_parallel_compose(
            left,
            right,
            lhs_breadcrumb=lhs_breadcrumb,
            rhs_breadcrumb=rhs_breadcrumb,
        )
    if kind == CONCAT:
        return _concat_legacy(left, right)
    raise AssertionError(f"unknown node kind {kind}")


class ArenaMorphism:
    """Morphism-compatible root handle over a shared append-only arena."""

    __slots__ = ("_arena", "_root")

    def __init__(
        self,
        lanes=None,
        _duration_cycles: int | Expr = -1,
        *,
        _arena: MorphismArena | None = None,
        _root: int | None = None,
    ) -> None:
        if _arena is not None and _root is not None:
            self._arena = _arena
            self._root = _root
            return
        arena = _ACTIVE_ARENA.get() or MorphismArena()
        if _duration_cycles == -1 and lanes is not None and len(lanes) == 1:
            channel, lane = next(iter(lanes.items()))
            if (
                isinstance(lane, LegacyLane)
                and len(lane.operations) == 1
                and isinstance(lane.operations[0], AtomicMorphism)
                and lane.operations[0].channel is channel
            ):
                self._arena = arena
                self._root = arena.add_atomic(lane.operations[0])
                return
        legacy = LegacyMorphism(
            {} if lanes is None else lanes,
            _duration_cycles=_duration_cycles,
        )
        self._arena = arena
        self._root = arena.add_leaf(legacy)

    @classmethod
    def _from_root(cls, arena: MorphismArena, root: int) -> "ArenaMorphism":
        return cls(_arena=arena, _root=root)

    @classmethod
    def from_atomic(cls, operation: AtomicMorphism) -> "ArenaMorphism":
        arena = _ACTIVE_ARENA.get() or MorphismArena()
        return cls._from_root(arena, arena.add_atomic(operation))

    def _coerce(self, other: "ArenaMorphism") -> int:
        if other._arena is self._arena:
            return other._root
        return self._arena.add_leaf(other._arena.materialize(other._root))

    def _binary(
        self,
        other: "ArenaMorphism",
        kind: int,
        *,
        breadcrumbs=None,
    ) -> "ArenaMorphism":
        right = self._coerce(other)
        root = self._arena.add_binary(kind, self._root, right)
        self._arena.payload[root] = breadcrumbs
        return ArenaMorphism._from_root(self._arena, root)

    def _legacy(self) -> LegacyMorphism:
        return self._arena.materialize(self._root)

    @property
    def lanes(self):
        return self._legacy().lanes

    @property
    def channels(self):
        return self._arena.channels(
            self._arena.summaries[self._root].channel_mask
        )

    def state_summary(self, channel) -> ChannelStateSummary | None:
        return self._arena.query_state(self._root, channel)

    def initial_state(self, channel):
        summary = self.state_summary(channel)
        return None if summary is None else summary.initial_state

    def end_state(self, channel):
        summary = self.state_summary(channel)
        return None if summary is None else summary.end_state

    def effective_end_state(self, channel):
        summary = self.state_summary(channel)
        return None if summary is None else summary.effective_end_state

    def end_states(self):
        result = {}
        for channel in self.channels:
            state = self.end_state(channel)
            if state is not None:
                result[channel] = state
        return result

    @property
    def total_duration_expr(self):
        duration = self._arena.summaries[self._root].duration
        if duration is None:
            return self._legacy().total_duration_expr
        if isinstance(duration, Expr):
            if self._arena.binding_env is not None:
                return duration.resolve(None, self._arena.binding_env)
            return duration
        return duration if duration >= 0 else 0

    @property
    def total_duration_cycles(self) -> int:
        duration = self.total_duration_expr
        if isinstance(duration, Expr):
            raise TypeError("Morphism duration is symbolic")
        return duration

    @property
    def total_duration_us(self) -> float:
        return cycles_to_time(self.total_duration_cycles) / us

    def lanes_by_board(self):
        return self._legacy().lanes_by_board()

    def __rshift__(self, other):
        if isinstance(other, AtomicMorphism):
            other = ArenaMorphism.from_atomic(other)
        if isinstance(other, ArenaMorphism):
            compose_id = next_compose_id()
            return self._binary(
                other,
                AUTO,
                breadcrumbs=(
                    compose_breadcrumb("serial", "lhs", compose_id, stacklevel=1),
                    compose_breadcrumb("serial", "rhs", compose_id, stacklevel=1),
                ),
            )

        from catseq.morphism.deferred import MorphismDef

        if isinstance(other, MorphismDef):
            return other(self)
        if isinstance(other, dict):
            if not all(hasattr(key, "global_id") for key in other):
                return NotImplemented
            return self._apply_channel_operations(other)
        return NotImplemented

    def __matmul__(self, other):
        if isinstance(other, AtomicMorphism):
            other = ArenaMorphism.from_atomic(other)
        if not isinstance(other, ArenaMorphism):
            return NotImplemented
        compose_id = next_compose_id()
        return self._binary(
            other,
            STRICT,
            breadcrumbs=(
                compose_breadcrumb("strict", "lhs", compose_id, stacklevel=1),
                compose_breadcrumb("strict", "rhs", compose_id, stacklevel=1),
            ),
        )

    def __or__(self, other):
        if isinstance(other, AtomicMorphism):
            other = ArenaMorphism.from_atomic(other)
        if not isinstance(other, ArenaMorphism):
            return NotImplemented
        compose_id = next_compose_id()
        return self._binary(
            other,
            PARALLEL,
            breadcrumbs=(
                compose_breadcrumb("parallel", "lhs", compose_id, stacklevel=1),
                compose_breadcrumb("parallel", "rhs", compose_id, stacklevel=1),
            ),
        )

    def _apply_channel_operations(self, operations, application_breadcrumbs=None):
        return _arena_apply_deferred(
            self,
            operations,
            application_breadcrumbs=application_breadcrumbs,
        )

    def __str__(self) -> str:
        return str(self._legacy())

    def lanes_view(self) -> str:
        return self._legacy().lanes_view()

    def timeline_view(self, compact: bool = True) -> str:
        return self._legacy().timeline_view(compact=compact)


class ArenaEndStateView(Mapping):
    """Lazy mapping that keeps an end-state dependency attached to its DAG root."""

    __slots__ = ("morphism",)

    def __init__(self, morphism: ArenaMorphism) -> None:
        self.morphism = morphism

    def __getitem__(self, channel):
        state = self.morphism.end_state(channel)
        if state is None:
            raise KeyError(channel)
        return state

    def __iter__(self):
        return iter(self.morphism.channels)

    def __len__(self) -> int:
        return len(self.morphism.channels)


_ORIGINAL_APPLY_DEFERRED = None
_ORIGINAL_MORPHISM_DEF_CALL = None
_ORIGINAL_REPEAT_MORPHISM = None


def _arena_from_atomic(operation: AtomicMorphism) -> ArenaMorphism:
    return ArenaMorphism.from_atomic(operation)


def _arena_repeat_morphism(morphism, count, assembler_sequence):
    if not isinstance(morphism, ArenaMorphism):
        return _ORIGINAL_REPEAT_MORPHISM(
            morphism,
            count,
            assembler_sequence,
        )
    root = morphism._arena.add_repeat(
        morphism._root,
        count,
        assembler_sequence,
    )
    return ArenaMorphism._from_root(morphism._arena, root)


def _arena_apply_deferred(
    base,
    operations,
    application_breadcrumbs=None,
):
    if not isinstance(base, ArenaMorphism):
        return _ORIGINAL_APPLY_DEFERRED(
            base,
            operations,
            application_breadcrumbs=application_breadcrumbs,
        )

    for channel in operations:
        if channel not in base.channels:
            available = [item.global_id for item in base.channels]
            raise ValueError(
                f"Channel {channel.global_id} not found in morphism. "
                f"Available channels: {available}"
            )
    if not operations:
        return base
    root = base._arena.add_deferred_apply(
        base._root,
        operations,
        application_breadcrumbs,
    )
    return ArenaMorphism._from_root(base._arena, root)


def _arena_morphism_def_call(
    self,
    target,
    start_state=None,
    *,
    application_breadcrumb=None,
):
    if isinstance(target, Channel):
        arena = _ACTIVE_ARENA.get() or MorphismArena()
        root = arena.add_deferred_channel(self, target, start_state)
        return ArenaMorphism._from_root(arena, root)
    if not isinstance(target, ArenaMorphism):
        return _ORIGINAL_MORPHISM_DEF_CALL(
            self,
            target,
            start_state,
            application_breadcrumb=application_breadcrumb,
        )
    breadcrumbs = {
        channel: (application_breadcrumb,)
        if application_breadcrumb is not None
        else ()
        for channel in target.channels
    }
    return _arena_apply_deferred(
        target,
        {channel: self for channel in target.channels},
        application_breadcrumbs=breadcrumbs,
    )


def _arena_get_end_state(morphism):
    if isinstance(morphism, ArenaMorphism):
        return ArenaEndStateView(morphism)
    return _ORIGINAL_GET_END_STATE(morphism)


def _arena_dict_to_morphism(operations, start_state):
    if not isinstance(start_state, ArenaEndStateView):
        return _ORIGINAL_DICT_TO_MORPHISM(operations, start_state)
    source = start_state.morphism
    for channel in operations:
        if channel not in source.channels:
            raise KeyError(channel)
    root = source._arena.add_deferred_batch(source._root, operations)
    return ArenaMorphism._from_root(source._arena, root)


def _arena_get_start_state(morphism):
    if isinstance(morphism, ArenaMorphism):
        result = {}
        for channel in morphism.channels:
            state = morphism.initial_state(channel)
            if state is not None:
                result[channel] = state
        return result
    return _ORIGINAL_GET_START_STATE(morphism)


def _arena_get_end_idle_morphism(morphism):
    if not isinstance(morphism, ArenaMorphism):
        return _ORIGINAL_GET_END_IDLE_MORPHISM(morphism)
    import rb1system.utils as utils

    channel_operations = {
        channel: utils.hold(1 * utils.us) for channel in morphism.channels
    }
    return utils.dict_to_morphism(
        channel_operations,
        ArenaEndStateView(morphism),
    )


_ORIGINAL_GET_END_STATE = None
_ORIGINAL_GET_START_STATE = None
_ORIGINAL_GET_END_IDLE_MORPHISM = None
_ORIGINAL_DICT_TO_MORPHISM = None


def install() -> None:
    """Replace already-imported Morphism aliases for this process only."""

    global _ORIGINAL_APPLY_DEFERRED
    global _ORIGINAL_GET_END_IDLE_MORPHISM
    global _ORIGINAL_GET_END_STATE
    global _ORIGINAL_GET_START_STATE
    global _ORIGINAL_DICT_TO_MORPHISM
    global _ORIGINAL_MORPHISM_DEF_CALL
    global _ORIGINAL_REPEAT_MORPHISM

    import catseq.morphism.deferred as deferred
    import catseq.morphism.compose as compose
    import catseq.debug as debug
    import catseq.control as control

    if _ORIGINAL_APPLY_DEFERRED is None:
        _ORIGINAL_APPLY_DEFERRED = deferred._apply_deferred_operations
    if _ORIGINAL_MORPHISM_DEF_CALL is None:
        _ORIGINAL_MORPHISM_DEF_CALL = deferred.MorphismDef.__call__
    if _ORIGINAL_REPEAT_MORPHISM is None:
        _ORIGINAL_REPEAT_MORPHISM = control.repeat_morphism
    deferred._apply_deferred_operations = _arena_apply_deferred
    deferred.MorphismDef.__call__ = _arena_morphism_def_call
    compose.annotate_morphism = _legacy_annotate
    debug.capture_callsite = _cached_capture_callsite
    control.repeat_morphism = _arena_repeat_morphism

    replacements = {
        legacy_from_atomic: _arena_from_atomic,
        _ORIGINAL_REPEAT_MORPHISM: _arena_repeat_morphism,
    }
    try:
        import rb1system.utils as utils
    except ImportError:
        utils = None
    if utils is not None:
        if _ORIGINAL_GET_END_STATE is None:
            _ORIGINAL_GET_END_STATE = utils.get_end_state
            _ORIGINAL_GET_START_STATE = utils.get_start_state
            _ORIGINAL_GET_END_IDLE_MORPHISM = utils.get_end_idle_morphism
            _ORIGINAL_DICT_TO_MORPHISM = utils.dict_to_morphism
        replacements.update(
            {
                _ORIGINAL_DICT_TO_MORPHISM: _arena_dict_to_morphism,
                _ORIGINAL_GET_END_STATE: _arena_get_end_state,
                _ORIGINAL_GET_START_STATE: _arena_get_start_state,
                _ORIGINAL_GET_END_IDLE_MORPHISM: _arena_get_end_idle_morphism,
            }
        )
        utils.get_end_state = _arena_get_end_state
        utils.get_start_state = _arena_get_start_state
        utils.get_end_idle_morphism = _arena_get_end_idle_morphism
        utils.dict_to_morphism = _arena_dict_to_morphism

    this_module = sys.modules[__name__]
    for module_name, module in tuple(sys.modules.items()):
        if module is None or module is this_module:
            continue
        if module_name == "catseq.morphism.compose":
            continue
        namespace = getattr(module, "__dict__", None)
        if namespace is None:
            continue
        for name, value in tuple(namespace.items()):
            if value is LegacyMorphism:
                setattr(module, name, ArenaMorphism)
                continue
            for original, replacement in replacements.items():
                if value is original:
                    setattr(module, name, replacement)
                    break


@contextmanager
def build_arena() -> Iterator[MorphismArena]:
    arena = MorphismArena()
    token = _ACTIVE_ARENA.set(arena)
    try:
        yield arena
    finally:
        _ACTIVE_ARENA.reset(token)
