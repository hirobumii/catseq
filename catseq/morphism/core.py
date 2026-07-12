"""Arena-backed Morphism root handles and compatibility views."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterable
from dataclasses import dataclass
from functools import wraps
from typing import Callable, Iterator, Mapping, ParamSpec, TypeVar, cast

from ..debug import (
    annotate_atomic,
    compose_breadcrumb,
    dict_apply_breadcrumb,
    next_compose_id,
)
from ..expr import Expr, contains_expr, structurally_equal
from ..lanes import Lane, LaneOperation
from ..time_utils import cycles_to_time, time_to_cycles, us
from ..types.common import (
    AtomicMorphism,
    Board,
    Channel,
    DebugBreadcrumb,
    OperationType,
    State,
    TimedRegion,
)
from .arena import (
    ArenaOperation,
    ArenaProgram,
    DeferredRepeat,
    NodeId,
    NodeKind,
    ProgramArena,
)
from .views import lanes_view as render_lanes_view
from .views import morphism_str, timeline_view as render_timeline_view


_ACTIVE_ARENA: ContextVar[ProgramArena | None] = ContextVar(
    "catseq_active_morphism_arena",
    default=None,
)
_P = ParamSpec("_P")
_R = TypeVar("_R")


@contextmanager
def _arena_scope(arena: ProgramArena | None = None) -> Iterator[ProgramArena]:
    current = _ACTIVE_ARENA.get()
    selected = arena or current or ProgramArena()
    if current is selected:
        yield selected
        return
    token = _ACTIVE_ARENA.set(selected)
    try:
        yield selected
    finally:
        _ACTIVE_ARENA.reset(token)


def arena_build(builder: Callable[_P, _R]) -> Callable[_P, _R]:
    """Give one unchanged sequence-builder call an isolated append-only arena."""

    @wraps(builder)
    def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with _arena_scope(ProgramArena()):
            return builder(*args, **kwargs)

    return wrapped


@dataclass(frozen=True, slots=True)
class _LaneRef:
    root: NodeId | None
    duration: int | Expr
    initial_state: State | None
    end_state: State | None
    effective_start_state: State | None
    effective_end_state: State | None
    has_effective: bool


def _lane_ref(root: NodeId | None, lane: Lane) -> _LaneRef:
    return _LaneRef(
        root=root,
        duration=lane.total_duration_expr,
        initial_state=lane.initial_state,
        end_state=lane.end_state,
        effective_start_state=lane.effective_start_state,
        effective_end_state=lane.effective_end_state,
        has_effective=any(
            getattr(operation, "operation_type", None) != OperationType.IDENTITY
            for operation in lane.operations
        ),
    )


def _unresolved_lane_refs(
    channels: Iterable[Channel],
) -> dict[Channel, _LaneRef]:
    """Keep channel identity without pretending boundary summaries are known."""
    return {
        channel: _LaneRef(
            root=None,
            duration=0,
            initial_state=None,
            end_state=None,
            effective_start_state=None,
            effective_end_state=None,
            has_effective=False,
        )
        for channel in channels
    }


def _concatenate_lane_duration(
    arena: ProgramArena,
    left_duration: int | Expr,
    right: _LaneRef,
) -> int | Expr:
    if not isinstance(left_duration, Expr) and not isinstance(right.duration, Expr):
        return left_duration + right.duration
    if right.root is None:
        return left_duration
    program = arena.freeze(right.root)
    duration = left_duration
    stack: list[tuple[ArenaProgram, NodeId]] = [(program, right.root)]
    while stack:
        current, node_id = stack.pop()
        kind = current.kinds[node_id]
        if kind == NodeKind.ATOMIC:
            operation = current.payload[node_id]
            if not isinstance(operation, (AtomicMorphism, TimedRegion)):
                raise TypeError(f"Atomic node {node_id} has invalid payload")
            duration = duration + operation.duration_cycles
            continue
        if kind in {NodeKind.AUTO_SERIAL, NodeKind.STRICT_SERIAL}:
            stack.append((current, current.right[node_id]))
            stack.append((current, current.left[node_id]))
            continue
        if kind == NodeKind.ANNOTATE:
            stack.append((current, current.left[node_id]))
            continue
        if kind == NodeKind.REFERENCE:
            reference = current.payload[node_id]
            referenced_program = getattr(reference, "program", None)
            referenced_root = getattr(reference, "root", None)
            if not isinstance(referenced_program, ArenaProgram) or not isinstance(
                referenced_root,
                int,
            ):
                raise TypeError(f"Reference node {node_id} has invalid payload")
            stack.append((referenced_program, referenced_root))
            continue
        if kind == NodeKind.WAIT:
            wait_duration = current.payload[node_id]
            if not isinstance(wait_duration, (int, Expr)):
                raise TypeError(f"Wait node {node_id} has invalid payload")
            duration = duration + wait_duration
            continue
        raise TypeError(f"Lane root contains unsupported {kind.name} node")
    return duration


class Morphism:
    """Immutable logical timeline represented by an append-only arena root."""

    __slots__ = (
        "_arena",
        "_duration_cycles",
        "_lane_refs",
        "_lanes_cache",
        "_realized_cache",
        "_root",
        "_summaries_resolved",
    )

    def __init__(
        self,
        lanes: Mapping[Channel, Lane] | None = None,
        _duration_cycles: int | Expr = -1,
        *,
        _arena: ProgramArena | None = None,
        _root: NodeId | None = None,
        _lane_refs: Mapping[Channel, _LaneRef] | None = None,
        _summaries_resolved: bool = True,
    ) -> None:
        if _arena is not None and _root is not None and _lane_refs is not None:
            self._arena = _arena
            self._root = _root
            self._lane_refs = dict(_lane_refs)
            self._duration_cycles = _duration_cycles
            self._lanes_cache: dict[Channel, Lane] | None = None
            self._summaries_resolved = _summaries_resolved
            self._realized_cache: Morphism | None = None
            return

        source_lanes = {} if lanes is None else dict(lanes)
        duration = self._validate_lane_durations(source_lanes, _duration_cycles)
        arena = _ACTIVE_ARENA.get() or ProgramArena()
        refs: dict[Channel, _LaneRef] = {}
        roots: list[NodeId] = []
        for channel, lane in source_lanes.items():
            lane_root: NodeId | None = None
            for operation in lane.operations:
                operation_channel = getattr(operation, "channel", channel)
                if operation_channel != channel:
                    raise ValueError(
                        f"Lane {channel.global_id} contains operation for "
                        f"{getattr(operation_channel, 'global_id', None)!r}"
                    )
                if isinstance(operation, (AtomicMorphism, TimedRegion)) and hasattr(
                    operation,
                    "channel",
                ):
                    atomic_root = arena.atomic(operation)
                else:
                    atomic_root = arena._wait_cycles(
                        getattr(operation, "duration_cycles", 0)
                    )
                lane_root = (
                    atomic_root
                    if lane_root is None
                    else arena.serial(lane_root, atomic_root)
                )
            refs[channel] = _lane_ref(lane_root, lane)
            if lane_root is not None:
                roots.append(lane_root)

        if roots:
            root = roots[0]
            for other_root in roots[1:]:
                root = arena.parallel(root, other_root)
        else:
            root = arena._wait_cycles(duration if duration >= 0 else 0)

        self._arena = arena
        self._root = root
        self._lane_refs = refs
        self._duration_cycles = duration
        self._lanes_cache = source_lanes
        self._summaries_resolved = True
        self._realized_cache = None

    @staticmethod
    def _validate_lane_durations(
        lanes: Mapping[Channel, Lane],
        empty_duration: int | Expr,
    ) -> int | Expr:
        if not lanes:
            return empty_duration
        reference = next(iter(lanes.values())).total_duration_expr
        mismatched = [
            lane.total_duration_expr
            for lane in lanes.values()
            if not structurally_equal(lane.total_duration_expr, reference)
        ]
        if mismatched:
            raise ValueError(
                "All lanes must have equal duration for parallel composition. "
                f"Got: {[reference, *mismatched]}"
            )
        return reference

    @classmethod
    def _from_parts(
        cls,
        arena: ProgramArena,
        root: NodeId,
        lane_refs: Mapping[Channel, _LaneRef],
        duration: int | Expr,
        *,
        summaries_resolved: bool = True,
    ) -> Morphism:
        return cls(
            _arena=arena,
            _root=root,
            _lane_refs=lane_refs,
            _duration_cycles=duration,
            _summaries_resolved=summaries_resolved,
        )

    @classmethod
    def _from_wait_cycles(cls, duration: int | Expr) -> Morphism:
        arena = _ACTIVE_ARENA.get() or ProgramArena()
        root = arena._wait_cycles(duration)
        return cls._from_parts(arena, root, {}, duration)

    @property
    def arena_program(self) -> ArenaProgram:
        """Return an immutable-length view used by the DAG-native compiler."""
        if self._realized_cache is not None:
            return self._realized_cache.arena_program
        return self._arena._consolidate(self._root)

    def _realized(self) -> Morphism:
        """Lower deferred nodes only for explicit compatibility inspection."""
        if self._summaries_resolved:
            return self
        if self._realized_cache is None:
            from .lower import materialize_deferred_program

            self._realized_cache = materialize_deferred_program(
                self.arena_program
            )
        return self._realized_cache

    def _contains_expr(self) -> bool:
        if not self._summaries_resolved:
            return self._realized()._contains_expr()
        program = self.arena_program
        reachable: set[NodeId] = set()
        stack = [program.root]
        while stack:
            node_id = stack.pop()
            if node_id in reachable:
                continue
            reachable.add(node_id)
            if contains_expr(program.payload[node_id]):
                return True
            left = program.left[node_id]
            right = program.right[node_id]
            if left >= 0:
                stack.append(left)
            if right >= 0:
                stack.append(right)
        return False

    @property
    def channels(self) -> tuple[Channel, ...]:
        return tuple(self._lane_refs)

    def state_for(self, channel: Channel) -> _LaneRef | None:
        """Return the cached boundary summary for one channel."""
        if not self._summaries_resolved:
            return self._realized().state_for(channel)
        return self._lane_refs.get(channel)

    def initial_state(self, channel: Channel) -> State | None:
        if not self._summaries_resolved:
            return self._realized().initial_state(channel)
        summary = self._lane_refs.get(channel)
        return None if summary is None else summary.initial_state

    def end_state(self, channel: Channel) -> State | None:
        if not self._summaries_resolved:
            return self._realized().end_state(channel)
        summary = self._lane_refs.get(channel)
        return None if summary is None else summary.end_state

    def effective_end_state(self, channel: Channel) -> State | None:
        if not self._summaries_resolved:
            return self._realized().effective_end_state(channel)
        summary = self._lane_refs.get(channel)
        return None if summary is None else summary.effective_end_state

    @property
    def lanes(self) -> dict[Channel, Lane]:
        """Materialize the legacy per-channel view on explicit access."""
        if not self._summaries_resolved:
            return self._realized().lanes
        if self._lanes_cache is None:
            program = self._arena.freeze(self._root)
            self._lanes_cache = {
                channel: Lane(self._materialize_lane(program, lane_ref.root))
                for channel, lane_ref in self._lane_refs.items()
            }
        return self._lanes_cache

    @staticmethod
    def _materialize_lane(
        program: ArenaProgram,
        root: NodeId | None,
    ) -> tuple[LaneOperation, ...]:
        if root is None:
            return ()
        operations: list[LaneOperation] = []
        stack: list[
            tuple[ArenaProgram, NodeId, tuple[DebugBreadcrumb, ...]]
        ] = [(program, root, ())]
        while stack:
            current, node_id, breadcrumbs = stack.pop()
            kind = current.kinds[node_id]
            if kind == NodeKind.ATOMIC:
                operation = current.payload[node_id]
                if not isinstance(operation, (AtomicMorphism, TimedRegion)):
                    raise TypeError(f"Atomic node {node_id} has invalid payload")
                operations.append(annotate_atomic(operation, breadcrumbs))
                continue
            if kind == NodeKind.WAIT:
                continue
            if kind in {NodeKind.AUTO_SERIAL, NodeKind.STRICT_SERIAL}:
                right_breadcrumb = current.payload[node_id]
                right_breadcrumbs = breadcrumbs
                if isinstance(right_breadcrumb, DebugBreadcrumb):
                    right_breadcrumbs = (right_breadcrumb,) + breadcrumbs
                stack.append(
                    (current, current.right[node_id], right_breadcrumbs)
                )
                stack.append((current, current.left[node_id], breadcrumbs))
                continue
            if kind == NodeKind.ANNOTATE:
                node_breadcrumbs = current.payload[node_id]
                if not isinstance(node_breadcrumbs, tuple):
                    raise TypeError(f"Annotate node {node_id} has invalid payload")
                stack.append(
                    (
                        current,
                        current.left[node_id],
                        node_breadcrumbs + breadcrumbs,
                    )
                )
                continue
            if kind == NodeKind.REFERENCE:
                reference = current.payload[node_id]
                referenced_program = getattr(reference, "program", None)
                referenced_root = getattr(reference, "root", None)
                if not isinstance(referenced_program, ArenaProgram) or not isinstance(
                    referenced_root,
                    int,
                ):
                    raise TypeError(f"Reference node {node_id} has invalid payload")
                stack.append(
                    (referenced_program, referenced_root, breadcrumbs)
                )
                continue
            raise TypeError(f"Lane root contains unsupported {kind.name} node")
        return tuple(operations)

    def _import_into(
        self,
        arena: ProgramArena,
    ) -> tuple[NodeId, dict[Channel, _LaneRef]]:
        if arena is self._arena:
            return self._root, dict(self._lane_refs)
        if not self._summaries_resolved:
            program = self._arena.freeze(self._root)
            imported_root = arena._reference(
                program,
                self._root,
                channels=self.channels,
            )
            return imported_root, dict(self._lane_refs)
        channels_with_roots = [
            (channel, lane_ref)
            for channel, lane_ref in self._lane_refs.items()
            if lane_ref.root is not None
        ]
        program = self._arena.freeze(self._root)
        imported_root = arena._reference(
            program,
            self._root,
            channels=self.channels,
        )
        imported_lane_roots = tuple(
            arena._reference(program, lane_ref.root, channels=(channel,))
            for channel, lane_ref in channels_with_roots
            if lane_ref.root is not None
        )
        imported = (imported_root, *imported_lane_roots)
        imported_refs = dict(self._lane_refs)
        for (channel, lane_ref), root in zip(
            channels_with_roots,
            imported[1:],
            strict=True,
        ):
            imported_refs[channel] = _LaneRef(
                root=root,
                duration=lane_ref.duration,
                initial_state=lane_ref.initial_state,
                end_state=lane_ref.end_state,
                effective_start_state=lane_ref.effective_start_state,
                effective_end_state=lane_ref.effective_end_state,
                has_effective=lane_ref.has_effective,
            )
        return imported[0], imported_refs

    def _annotated(self, breadcrumbs: tuple[DebugBreadcrumb, ...]) -> Morphism:
        if not breadcrumbs or not self._lane_refs:
            return self
        root = self._arena._annotate(self._root, breadcrumbs)
        if not self._summaries_resolved:
            return Morphism._from_parts(
                self._arena,
                root,
                self._lane_refs,
                -1,
                summaries_resolved=False,
            )
        refs = {
            channel: _LaneRef(
                root=(
                    None
                    if lane_ref.root is None
                    else self._arena._annotate(lane_ref.root, breadcrumbs)
                ),
                duration=lane_ref.duration,
                initial_state=lane_ref.initial_state,
                end_state=lane_ref.end_state,
                effective_start_state=lane_ref.effective_start_state,
                effective_end_state=lane_ref.effective_end_state,
                has_effective=lane_ref.has_effective,
            )
            for channel, lane_ref in self._lane_refs.items()
        }
        return Morphism._from_parts(
            self._arena,
            root,
            refs,
            self._duration_cycles,
        )

    @property
    def total_duration_cycles(self) -> int:
        """Return total duration in hardware cycles."""
        if not self._summaries_resolved:
            return self._realized().total_duration_cycles
        if isinstance(self._duration_cycles, Expr):
            raise TypeError(
                "Morphism duration is symbolic; realize or bind it before requesting cycles."
            )
        return self._duration_cycles if self._duration_cycles >= 0 else 0

    @property
    def total_duration_expr(self) -> int | Expr:
        if not self._summaries_resolved:
            return self._realized().total_duration_expr
        if isinstance(self._duration_cycles, Expr):
            return self._duration_cycles
        return self._duration_cycles if self._duration_cycles >= 0 else 0

    @property
    def total_duration_us(self) -> float:
        """Return total duration in microseconds."""
        return cycles_to_time(self.total_duration_cycles) / us

    def lanes_by_board(self) -> dict[Board, dict[Channel, Lane]]:
        """Group the compatibility Lane view by board."""
        result: dict[Board, dict[Channel, Lane]] = {}
        for channel, lane in self.lanes.items():
            result.setdefault(channel.board, {})[channel] = lane
        return result

    def select_channels(self, channels: tuple[Channel, ...]) -> Morphism:
        """Create a structure-sharing subprogram for the selected channels."""
        if not self._summaries_resolved:
            return self._realized().select_channels(channels)
        refs = {
            channel: self._lane_refs[channel]
            for channel in channels
            if channel in self._lane_refs
        }
        roots = [
            lane_ref.root
            for lane_ref in refs.values()
            if lane_ref.root is not None
        ]
        if not roots:
            return Morphism._from_wait_cycles(0)
        root = roots[0]
        for other_root in roots[1:]:
            root = self._arena.parallel(root, other_root)
        duration = next(iter(refs.values())).duration
        return Morphism._from_parts(self._arena, root, refs, duration)

    def _append_channel_suffixes(
        self,
        suffixes: Mapping[Channel, Morphism],
        duration: int | Expr,
    ) -> Morphism:
        """Append one already-aligned suffix per channel without Morphism fan-out."""
        suffix_roots: list[NodeId] = []
        suffix_refs: dict[Channel, _LaneRef] = {}
        for channel, suffix in suffixes.items():
            suffix_root, imported_refs = suffix._import_into(self._arena)
            suffix_roots.append(suffix_root)
            suffix_refs[channel] = imported_refs[channel]
        if not suffix_roots:
            return self
        suffix_root = suffix_roots[0]
        for other_root in suffix_roots[1:]:
            suffix_root = self._arena.parallel(suffix_root, other_root)
        root = self._arena.serial(self._root, suffix_root)
        result_refs: dict[Channel, _LaneRef] = {}
        for channel, left in self._lane_refs.items():
            right = suffix_refs[channel]
            if left.root is None:
                result_refs[channel] = right
                continue
            if right.root is None:
                result_refs[channel] = left
                continue
            result_refs[channel] = _LaneRef(
                root=self._arena.serial(left.root, right.root),
                duration=_concatenate_lane_duration(
                    self._arena,
                    left.duration,
                    right,
                ),
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
        result_duration = next(iter(result_refs.values())).duration
        return Morphism._from_parts(
            self._arena,
            root,
            result_refs,
            result_duration,
        )

    def __matmul__(self, other: object) -> Morphism:
        """Compose with strict state matching, checked during compilation."""
        from .compose import strict_compose_morphisms

        if isinstance(other, (AtomicMorphism, TimedRegion)):
            other = from_atomic(other)
        if not isinstance(other, Morphism):
            return NotImplemented
        compose_id = next_compose_id()
        return strict_compose_morphisms(
            self,
            other,
            lhs_breadcrumb=compose_breadcrumb(
                "strict", "lhs", compose_id, stacklevel=1
            ),
            rhs_breadcrumb=compose_breadcrumb(
                "strict", "rhs", compose_id, stacklevel=1
            ),
        )

    def __rshift__(self, other: object) -> Morphism:
        """Compose sequentially with automatic state inference."""
        from .compose import auto_compose_morphisms
        from .deferred import MorphismDef

        if isinstance(other, (AtomicMorphism, TimedRegion)):
            other = from_atomic(other)
        if isinstance(other, Morphism):
            compose_id = next_compose_id()
            return auto_compose_morphisms(
                self,
                other,
                lhs_breadcrumb=compose_breadcrumb(
                    "serial", "lhs", compose_id, stacklevel=1
                ),
                rhs_breadcrumb=compose_breadcrumb(
                    "serial", "rhs", compose_id, stacklevel=1
                ),
            )
        if isinstance(other, MorphismDef):
            compose_id = next_compose_id()
            return other(
                self,
                application_breadcrumb=compose_breadcrumb(
                    "serial", "rhs", compose_id, stacklevel=1
                ),
            )
        if isinstance(other, dict):
            if not all(isinstance(key, Channel) for key in other):
                return NotImplemented
            if not all(isinstance(value, MorphismDef) for value in other.values()):
                return NotImplemented
            if not other:
                return self
            compose_id = next_compose_id()
            return self._apply_channel_operations(
                other,
                {
                    channel: (
                        dict_apply_breadcrumb(
                            channel.global_id,
                            compose_id,
                            stacklevel=1,
                        ),
                    )
                    for channel in other
                },
            )
        return NotImplemented

    def __or__(self, other: object) -> Morphism:
        """Compose independent channel sets in parallel."""
        from .compose import parallel_compose_morphisms

        if isinstance(other, (AtomicMorphism, TimedRegion)):
            other = from_atomic(other)
        if not isinstance(other, Morphism):
            return NotImplemented
        compose_id = next_compose_id()
        return parallel_compose_morphisms(
            self,
            other,
            lhs_breadcrumb=compose_breadcrumb(
                "parallel", "lhs", compose_id, stacklevel=1
            ),
            rhs_breadcrumb=compose_breadcrumb(
                "parallel", "rhs", compose_id, stacklevel=1
            ),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Morphism):
            return NotImplemented
        return (
            structurally_equal(self.total_duration_expr, other.total_duration_expr)
            and self.lanes == other.lanes
        )

    def __str__(self) -> str:
        return morphism_str(self)

    def lanes_view(self) -> str:
        """Generate the detailed per-channel compatibility view."""
        return render_lanes_view(self)

    def timeline_view(self, compact: bool = True) -> str:
        """Generate the compatibility timeline view."""
        return render_timeline_view(self, compact=compact)

    def _apply_channel_operations(
        self,
        channel_operations: Mapping[Channel, object],
        application_breadcrumbs: Mapping[
            Channel, tuple[DebugBreadcrumb, ...]
        ]
        | None = None,
    ) -> Morphism:
        from .deferred import MorphismDef, _record_deferred_operations

        return _record_deferred_operations(
            self,
            cast(dict[Channel, MorphismDef], dict(channel_operations)),
            (
                None
                if application_breadcrumbs is None
                else dict(application_breadcrumbs)
            ),
        )

    def _deferred_repeat(self, count: int, assembler_sequence: object) -> Morphism:
        root = self._arena.repeat(
            self._root,
            DeferredRepeat(count, assembler_sequence),
        )
        return Morphism._from_parts(
            self._arena,
            root,
            _unresolved_lane_refs(self.channels),
            -1,
            summaries_resolved=False,
        )


class MorphismEndStateView(Mapping[Channel, State]):
    """Lazy mapping that preserves a dependency on a Morphism DAG boundary."""

    __slots__ = ("morphism",)

    def __init__(self, morphism: Morphism) -> None:
        self.morphism = morphism

    def __getitem__(self, channel: Channel) -> State:
        state = self.morphism.end_state(channel)
        if state is None:
            raise KeyError(channel)
        return state

    def __iter__(self) -> Iterator[Channel]:
        return iter(self.morphism.channels)

    def __len__(self) -> int:
        return len(self.morphism.channels)


def from_atomic(op: ArenaOperation) -> Morphism:
    """Create an arena-backed Morphism from one channel-bound operation."""
    if op.channel is None:
        raise ValueError("Cannot create Morphism from an operation without a channel.")
    arena = _ACTIVE_ARENA.get() or ProgramArena()
    root = arena.atomic(op)
    has_effective = op.operation_type != OperationType.IDENTITY
    lane_ref = _LaneRef(
        root=root,
        duration=op.duration_cycles,
        initial_state=op.start_state,
        end_state=op.end_state,
        effective_start_state=op.start_state,
        effective_end_state=op.end_state,
        has_effective=has_effective,
    )
    return Morphism._from_parts(
        arena,
        root,
        {op.channel: lane_ref},
        op.duration_cycles,
    )


def identity(duration: float | Expr) -> Morphism:
    """Create a channel-free wait using SI seconds."""
    duration_cycles = time_to_cycles(duration)
    if not isinstance(duration_cycles, Expr) and duration_cycles < 0:
        raise ValueError("Identity duration must be non-negative.")
    return Morphism._from_wait_cycles(duration_cycles)
