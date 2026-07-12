"""Append-only Morphism arena used by the DAG-native compiler."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Generic, TypeAlias, TypeVar, overload

from ..expr import Expr
from ..time_utils import time_to_cycles
from ..types.common import AtomicMorphism, Channel, DebugBreadcrumb, TimedRegion


NodeId = int
ArenaOperation: TypeAlias = AtomicMorphism | TimedRegion
_T = TypeVar("_T")


class _PrefixView(Sequence[_T], Generic[_T]):
    """Immutable-length view over an append-only arena table."""

    __slots__ = ("_length", "_source")

    def __init__(self, source: list[_T], length: int) -> None:
        self._source = source
        self._length = length

    def __len__(self) -> int:
        return self._length

    @overload
    def __getitem__(self, index: int) -> _T: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[_T, ...]: ...

    def __getitem__(self, index: int | slice) -> _T | tuple[_T, ...]:
        if isinstance(index, slice):
            return tuple(self._source[: self._length][index])
        normalized = index if index >= 0 else self._length + index
        if not 0 <= normalized < self._length:
            raise IndexError(index)
        return self._source[normalized]

    def __iter__(self) -> Iterator[_T]:
        for index in range(self._length):
            yield self._source[index]


class NodeKind(IntEnum):
    ATOMIC = 0
    WAIT = 1
    AUTO_SERIAL = 2
    STRICT_SERIAL = 3
    PARALLEL = 4
    ANNOTATE = 5
    REFERENCE = 6


@dataclass(frozen=True, slots=True)
class _Reference:
    program: ArenaProgram
    root: NodeId


@dataclass(frozen=True, slots=True)
class ArenaProgram:
    """Immutable child-before-parent node table and selected root."""

    kinds: Sequence[NodeKind]
    left: Sequence[NodeId]
    right: Sequence[NodeId]
    payload: Sequence[object]
    channel_masks: Sequence[int]
    channels: Sequence[Channel]
    root: NodeId

    def __post_init__(self) -> None:
        node_count = len(self.kinds)
        if not 0 <= self.root < node_count:
            raise ValueError(f"Invalid arena root {self.root}")
        if not (
            len(self.left)
            == len(self.right)
            == len(self.payload)
            == len(self.channel_masks)
            == node_count
        ):
            raise ValueError("Arena node tables have different lengths")


class ProgramArena:
    """Mutable append surface; ``freeze`` creates the compiler input."""

    __slots__ = (
        "_channel_ids",
        "_channels",
        "_channel_masks",
        "_kinds",
        "_has_references",
        "_left",
        "_payload",
        "_right",
    )

    def __init__(self) -> None:
        self._kinds: list[NodeKind] = []
        self._has_references = False
        self._left: list[NodeId] = []
        self._right: list[NodeId] = []
        self._payload: list[object] = []
        self._channel_masks: list[int] = []
        self._channel_ids: dict[Channel, int] = {}
        self._channels: list[Channel] = []

    def _channel_bit(self, channel: Channel) -> int:
        channel_id = self._channel_ids.get(channel)
        if channel_id is None:
            channel_id = len(self._channels)
            self._channel_ids[channel] = channel_id
            self._channels.append(channel)
        return 1 << channel_id

    def _append(
        self,
        kind: NodeKind,
        left: NodeId,
        right: NodeId,
        payload: object,
        channel_mask: int,
    ) -> NodeId:
        node_id = len(self._kinds)
        if left >= node_id or right >= node_id:
            raise ValueError("Arena children must precede their parent")
        self._kinds.append(kind)
        self._left.append(left)
        self._right.append(right)
        self._payload.append(payload)
        self._channel_masks.append(channel_mask)
        return node_id

    def atomic(self, operation: ArenaOperation) -> NodeId:
        if operation.channel is None:
            raise ValueError("Atomic arena nodes require a channel")
        return self._append(
            NodeKind.ATOMIC,
            -1,
            -1,
            operation,
            self._channel_bit(operation.channel),
        )

    def wait(self, duration: float | Expr) -> NodeId:
        """Append a channel-free wait whose duration is in SI seconds."""
        if not isinstance(duration, Expr) and duration < 0:
            raise ValueError("Wait duration must be non-negative")
        return self._wait_cycles(time_to_cycles(duration))

    def _wait_cycles(self, duration_cycles: int | Expr) -> NodeId:
        if not isinstance(duration_cycles, Expr) and duration_cycles < 0:
            raise ValueError("Wait duration must be non-negative")
        return self._append(NodeKind.WAIT, -1, -1, duration_cycles, 0)

    def serial(
        self,
        left: NodeId,
        right: NodeId,
        *,
        strict: bool = False,
        right_breadcrumb: DebugBreadcrumb | None = None,
    ) -> NodeId:
        self._validate_children(left, right)
        kind = NodeKind.STRICT_SERIAL if strict else NodeKind.AUTO_SERIAL
        return self._append(
            kind,
            left,
            right,
            right_breadcrumb,
            self._channel_masks[left] | self._channel_masks[right],
        )

    def parallel(
        self,
        left: NodeId,
        right: NodeId,
        *,
        right_breadcrumb: DebugBreadcrumb | None = None,
    ) -> NodeId:
        self._validate_children(left, right)
        overlap = self._channel_masks[left] & self._channel_masks[right]
        if overlap:
            channels = [
                channel.global_id
                for channel_id, channel in enumerate(self._channels)
                if overlap & (1 << channel_id)
            ]
            raise ValueError(f"Cannot compose overlapping channels: {channels}")
        return self._append(
            NodeKind.PARALLEL,
            left,
            right,
            right_breadcrumb,
            self._channel_masks[left] | self._channel_masks[right],
        )

    def _annotate(
        self,
        child: NodeId,
        breadcrumbs: tuple[DebugBreadcrumb, ...],
    ) -> NodeId:
        self._validate_children(child, child)
        if not breadcrumbs:
            return child
        return self._append(
            NodeKind.ANNOTATE,
            child,
            -1,
            breadcrumbs,
            self._channel_masks[child],
        )

    def _reference(
        self,
        program: ArenaProgram,
        root: NodeId,
        *,
        channels: Sequence[Channel] | None = None,
    ) -> NodeId:
        """Append an O(1) edge to an immutable root in another arena."""
        target_mask = 0
        selected_channels: Iterator[Channel]
        if channels is None:
            source_mask = program.channel_masks[root]
            selected_channels = (
                channel
                for channel_id, channel in enumerate(program.channels)
                if source_mask & (1 << channel_id)
            )
        else:
            selected_channels = iter(channels)
        for channel in selected_channels:
            target_mask |= self._channel_bit(channel)
        self._has_references = True
        return self._append(
            NodeKind.REFERENCE,
            -1,
            -1,
            _Reference(program, root),
            target_mask,
        )

    def _consolidate(self, root: NodeId) -> ArenaProgram:
        """Flatten an arena forest with an explicit stack before compilation."""
        program = self.freeze(root)
        if not self._has_references:
            return program

        roots = [(program, root)]
        discovered: set[tuple[int, NodeId]] = set()
        programs: dict[int, ArenaProgram] = {id(program): program}
        order: list[tuple[int, NodeId]] = []
        stack: list[tuple[ArenaProgram, NodeId, bool]] = [
            (program, root, False)
        ]
        while stack:
            current, node_id, expanded = stack.pop()
            key = (id(current), node_id)
            programs[id(current)] = current
            if expanded:
                order.append(key)
                continue
            if key in discovered:
                continue
            discovered.add(key)
            stack.append((current, node_id, True))
            kind = current.kinds[node_id]
            if kind == NodeKind.REFERENCE:
                reference = current.payload[node_id]
                if not isinstance(reference, _Reference):
                    raise TypeError(f"Reference node {node_id} has invalid payload")
                stack.append((reference.program, reference.root, False))
                continue
            right = current.right[node_id]
            left = current.left[node_id]
            if right >= 0:
                stack.append((current, right, False))
            if left >= 0:
                stack.append((current, left, False))

        target = ProgramArena()
        mapped: dict[tuple[int, NodeId], NodeId] = {}
        for program_id, node_id in order:
            current = programs[program_id]
            kind = current.kinds[node_id]
            if kind == NodeKind.REFERENCE:
                reference = current.payload[node_id]
                if not isinstance(reference, _Reference):
                    raise TypeError(f"Reference node {node_id} has invalid payload")
                mapped[(program_id, node_id)] = mapped[
                    (id(reference.program), reference.root)
                ]
                continue
            if kind == NodeKind.ATOMIC:
                operation = current.payload[node_id]
                if not isinstance(operation, (AtomicMorphism, TimedRegion)):
                    raise TypeError(f"Atomic node {node_id} has invalid payload")
                target_id = target.atomic(operation)
            elif kind == NodeKind.WAIT:
                duration = current.payload[node_id]
                if not isinstance(duration, (int, Expr)):
                    raise TypeError(f"Wait node {node_id} has invalid payload")
                target_id = target._wait_cycles(duration)
            elif kind in {NodeKind.AUTO_SERIAL, NodeKind.STRICT_SERIAL}:
                breadcrumb = current.payload[node_id]
                target_id = target.serial(
                    mapped[(program_id, current.left[node_id])],
                    mapped[(program_id, current.right[node_id])],
                    strict=kind == NodeKind.STRICT_SERIAL,
                    right_breadcrumb=(
                        breadcrumb
                        if isinstance(breadcrumb, DebugBreadcrumb)
                        else None
                    ),
                )
            elif kind == NodeKind.PARALLEL:
                breadcrumb = current.payload[node_id]
                target_id = target.parallel(
                    mapped[(program_id, current.left[node_id])],
                    mapped[(program_id, current.right[node_id])],
                    right_breadcrumb=(
                        breadcrumb
                        if isinstance(breadcrumb, DebugBreadcrumb)
                        else None
                    ),
                )
            elif kind == NodeKind.ANNOTATE:
                breadcrumbs = current.payload[node_id]
                if not isinstance(breadcrumbs, tuple):
                    raise TypeError(f"Annotate node {node_id} has invalid payload")
                target_id = target._annotate(
                    mapped[(program_id, current.left[node_id])],
                    breadcrumbs,
                )
            else:
                raise TypeError(f"Unsupported arena node kind {kind}")
            mapped[(program_id, node_id)] = target_id

        consolidated_root = mapped[(id(roots[0][0]), roots[0][1])]
        return target.freeze(consolidated_root)

    def _validate_children(self, left: NodeId, right: NodeId) -> None:
        node_count = len(self._kinds)
        if not 0 <= left < node_count or not 0 <= right < node_count:
            raise ValueError(f"Invalid arena children ({left}, {right})")

    def freeze(self, root: NodeId) -> ArenaProgram:
        self._validate_children(root, root)
        node_count = len(self._kinds)
        return ArenaProgram(
            kinds=_PrefixView(self._kinds, node_count),
            left=_PrefixView(self._left, node_count),
            right=_PrefixView(self._right, node_count),
            payload=_PrefixView(self._payload, node_count),
            channel_masks=_PrefixView(self._channel_masks, node_count),
            channels=_PrefixView(self._channels, len(self._channels)),
            root=root,
        )
