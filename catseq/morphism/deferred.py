"""
Deferred morphism builders and application helpers.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator
from typing import Callable, Dict, Self

from ..expr import Expr, structurally_equal
from ..debug import (
    annotate_morphism,
    auto_generated_breadcrumb,
    deferred_apply_breadcrumb,
    deferred_definition_breadcrumb,
)
from ..types.common import (
    AtomicMorphism,
    Channel,
    DebugBreadcrumb,
    DebugFrame,
    OperationType,
    State,
    TimingKind,
    ChannelType,
)
from ..types.rwg import RWGUninitialized
from ..types.rsp import RSPUninitialized
from ..types.ttl import TTLState
from .arena import DeferredApplication, DeferredBatch, DeferredChannel
from .core import (
    Morphism,
    _ACTIVE_ARENA,
    _arena_scope,
    _unresolved_lane_refs,
    from_atomic,
)


_LOWERING_DEFERRED: ContextVar[bool] = ContextVar(
    "catseq_lowering_deferred",
    default=False,
)


@contextmanager
def _deferred_lowering_scope() -> Iterator[None]:
    token = _LOWERING_DEFERRED.set(True)
    try:
        yield
    finally:
        _LOWERING_DEFERRED.reset(token)


def _last_trace_frame(trace: tuple[DebugBreadcrumb, ...]) -> DebugFrame | None:
    for breadcrumb in reversed(trace):
        if breadcrumb.frame is not None:
            return breadcrumb.frame
    return None


class MorphismDef:
    """
    Represents a deferred-execution 'recipe' for a morphism.
    It wraps a generator function that produces a Morphism when provided
    with a channel and a starting state.
    """

    def __init__(
        self,
        generator: Callable[[Channel, State], Morphism] | None = None,
        generators: tuple[Callable[[Channel, State], Morphism], ...] | None = None,
        generator_traces: tuple[tuple[DebugBreadcrumb, ...], ...] | None = None,
    ):
        if generators is not None:
            self._generators = generators
        elif generator is not None:
            self._generators = (generator,)
        else:
            self._generators = ()

        if generator_traces is not None:
            self._generator_traces = generator_traces
        else:
            trace = (deferred_definition_breadcrumb(stacklevel=2),)
            self._generator_traces = tuple(trace for _ in self._generators)

    def __call__(
        self,
        target: "Channel | Morphism",
        start_state: "State | None" = None,
        *,
        application_breadcrumb: DebugBreadcrumb | None = None,
    ) -> Morphism:
        def _default_start_state(channel: Channel) -> State:
            if channel.channel_type == ChannelType.RWG:
                return RWGUninitialized()
            if channel.channel_type == ChannelType.RSP:
                return RSPUninitialized()
            if channel.channel_type == ChannelType.TTL:
                return TTLState.OFF
            raise ValueError(...)

        if isinstance(target, Channel):
            if start_state is None:
                start_state = _default_start_state(target)
            active_arena = _ACTIVE_ARENA.get()
            if active_arena is not None and not _LOWERING_DEFERRED.get():
                root = active_arena.deferred_channel(
                    target,
                    DeferredChannel(self, target, start_state),
                )
                return Morphism._from_parts(
                    active_arena,
                    root,
                    _unresolved_lane_refs((target,)),
                    -1,
                    summaries_resolved=False,
                )
            with _arena_scope():
                return self._execute_on_channel(target, start_state)

        if not isinstance(target, Morphism):
            raise TypeError(f"Target must be Channel or Morphism, got {type(target)}")
        return _record_deferred_operations(
            target,
            {channel: self for channel in target.channels},
            application_breadcrumbs={
                channel: (
                    (application_breadcrumb,)
                    if application_breadcrumb is not None
                    else ()
                )
                for channel in target.channels
            },
        )

    def __rshift__(self, other: Self) -> "MorphismDef":
        if not isinstance(other, MorphismDef):
            return NotImplemented
        return MorphismDef(
            generators=self._generators + other._generators,
            generator_traces=self._generator_traces + other._generator_traces,
        )

    def with_label(self, label: str) -> "MorphismDef":
        label_breadcrumb = DebugBreadcrumb(kind="label", label=label)
        return MorphismDef(
            generators=self._generators,
            generator_traces=tuple(
                trace + (label_breadcrumb,) for trace in self._generator_traces
            ),
        )

    def _execute_on_channel(self, channel: Channel, start_state: State) -> Morphism:
        current_state = start_state
        result: Morphism | None = None
        for generator_index, (generator, generator_trace) in enumerate(
            zip(self._generators, self._generator_traces, strict=True)
        ):
            morphism_piece = generator(channel, current_state)
            apply_breadcrumb = deferred_apply_breadcrumb(
                _last_trace_frame(generator_trace),
                channel.global_id,
                generator_index,
            )
            application_trace = generator_trace + (apply_breadcrumb,)
            if not morphism_piece.channels:
                piece_duration = morphism_piece.total_duration_expr
                if isinstance(piece_duration, Expr) or piece_duration > 0:
                    morphism_piece = from_atomic(
                        AtomicMorphism(
                            channel=channel,
                            start_state=current_state,
                            end_state=current_state,
                            duration_cycles=piece_duration,
                            operation_type=OperationType.IDENTITY,
                            timing_kind=TimingKind.DELAY,
                            debug_trace=(
                                auto_generated_breadcrumb("deferred_channelless_identity"),
                            )
                            + application_trace,
                        )
                    )
                else:
                    continue
            else:
                if channel not in morphism_piece.channels:
                    raise ValueError(
                        f"Deferred morphism for {channel.global_id} did not contain the target channel"
                    )
                morphism_piece = annotate_morphism(
                    morphism_piece,
                    application_trace,
                )
                current_state = (
                    morphism_piece.effective_end_state(channel) or current_state
                )
            result = morphism_piece if result is None else result >> morphism_piece
        return result or Morphism(lanes={}, _duration_cycles=0)


def _inferred_morphism_end_state(morphism: Morphism, channel: Channel, fallback: State) -> State:
    if channel not in morphism.channels:
        return fallback
    return morphism.effective_end_state(channel) or fallback


def _pad_channel_morphism(
    result_morphism: Morphism,
    channel: Channel,
    target_duration_cycles: int | Expr,
    application_trace: tuple[DebugBreadcrumb, ...] = (),
) -> Morphism:
    current_duration = result_morphism.total_duration_expr
    if structurally_equal(current_duration, target_duration_cycles):
        return result_morphism
    padding_cycles = target_duration_cycles - current_duration
    end_state = _inferred_morphism_end_state(result_morphism, channel, RWGUninitialized())
    padding_op = AtomicMorphism(
        channel=channel,
        start_state=end_state,
        end_state=end_state,
        duration_cycles=padding_cycles,
        operation_type=OperationType.IDENTITY,
        timing_kind=TimingKind.DELAY,
        debug_trace=(auto_generated_breadcrumb("deferred_padding"),) + application_trace,
    )
    return result_morphism >> from_atomic(padding_op)


def _record_deferred_operations(
    base_morphism: Morphism,
    channel_operations: Dict[Channel, MorphismDef],
    application_breadcrumbs: Dict[
        Channel, tuple[DebugBreadcrumb, ...]
    ]
    | None = None,
) -> Morphism:
    """Record template application without inspecting state or duration."""
    for channel in channel_operations:
        if channel not in base_morphism.channels:
            available_channels = [
                str(available.global_id) for available in base_morphism.channels
            ]
            raise ValueError(
                f"Channel {channel.global_id} not found in morphism. "
                f"Available channels: {available_channels}"
            )
    if not channel_operations:
        return base_morphism
    breadcrumbs = application_breadcrumbs or {}
    application = DeferredApplication(
        channel_operations=tuple(channel_operations.items()),
        application_breadcrumbs=tuple(
            (channel, breadcrumbs.get(channel, ()))
            for channel in channel_operations
        ),
    )
    root = base_morphism._arena.deferred_apply(
        base_morphism._root,
        application,
    )
    return Morphism._from_parts(
        base_morphism._arena,
        root,
        _unresolved_lane_refs(base_morphism.channels),
        -1,
        summaries_resolved=False,
    )


def deferred_batch_from_state_source(
    state_source: Morphism,
    channel_operations: Dict[Channel, MorphismDef],
) -> Morphism:
    """Build a standalone batch whose incoming states reference another root."""
    for channel in channel_operations:
        if channel not in state_source.channels:
            raise KeyError(channel)
    if not channel_operations:
        return Morphism._from_wait_cycles(0)
    payload = DeferredBatch(tuple(channel_operations.items()))
    root = state_source._arena.deferred_batch(state_source._root, payload)
    return Morphism._from_parts(
        state_source._arena,
        root,
        _unresolved_lane_refs(channel_operations.keys()),
        -1,
        summaries_resolved=False,
    )

def _apply_deferred_operations(
    base_morphism: Morphism,
    channel_operations: Dict[Channel, MorphismDef],
    application_breadcrumbs: Dict[Channel, tuple[DebugBreadcrumb, ...]] | None = None,
) -> Morphism:
    for channel in channel_operations.keys():
        if channel not in base_morphism.channels:
            available_channels = [str(ch.global_id) for ch in base_morphism.channels]
            raise ValueError(
                f"Channel {channel.global_id} not found in morphism. "
                f"Available channels: {available_channels}"
            )

    if not channel_operations:
        return base_morphism

    operation_results: Dict[Channel, Morphism] = {}
    max_duration_cycles: int | Expr = 0
    for channel, operation_def in channel_operations.items():
        end_state = _inferred_morphism_end_state(base_morphism, channel, RWGUninitialized())
        result_morphism = operation_def._execute_on_channel(channel, end_state)
        if application_breadcrumbs is not None:
            result_morphism = annotate_morphism(
                result_morphism,
                application_breadcrumbs.get(channel, ()),
            )
        operation_results[channel] = result_morphism
        result_duration = result_morphism.total_duration_expr
        if structurally_equal(max_duration_cycles, result_duration):
            continue
        if isinstance(result_duration, Expr) or isinstance(
            max_duration_cycles,
            Expr,
        ):
            max_duration_cycles = Expr.maximum(
                max_duration_cycles,
                result_duration,
            )
        else:
            max_duration_cycles = max(max_duration_cycles, result_duration)

    aligned_results = {
        channel: _pad_channel_morphism(
            result_morphism,
            channel,
            max_duration_cycles,
            application_breadcrumbs.get(channel, ()) if application_breadcrumbs is not None else (),
        )
        for channel, result_morphism in operation_results.items()
    }

    suffixes: dict[Channel, Morphism] = {}
    for channel in base_morphism.channels:
        if channel in aligned_results:
            channel_suffix = aligned_results[channel]
        else:
            end_state = _inferred_morphism_end_state(
                base_morphism,
                channel,
                RWGUninitialized(),
            )
            breadcrumb_trace: tuple[DebugBreadcrumb, ...] = ()
            if application_breadcrumbs is not None:
                breadcrumb_trace = application_breadcrumbs.get(
                    channel,
                    (),
                )
            wait_operation = AtomicMorphism(
                channel=channel,
                start_state=end_state,
                end_state=end_state,
                duration_cycles=max_duration_cycles,
                operation_type=OperationType.IDENTITY,
                timing_kind=TimingKind.DELAY,
                debug_trace=(auto_generated_breadcrumb("deferred_idle_alignment"),)
                + breadcrumb_trace,
            )
            channel_suffix = from_atomic(wait_operation)
        suffixes[channel] = channel_suffix

    return base_morphism._append_channel_suffixes(
        suffixes,
        max_duration_cycles,
    )
