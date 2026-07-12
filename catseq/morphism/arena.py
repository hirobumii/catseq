"""Append-only Morphism arena used by the DAG-native compiler."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from ..expr import Expr
from ..time_utils import time_to_cycles
from ..types.common import AtomicMorphism, Channel


NodeId = int


class NodeKind(IntEnum):
    ATOMIC = 0
    WAIT = 1
    AUTO_SERIAL = 2
    STRICT_SERIAL = 3
    PARALLEL = 4


@dataclass(frozen=True, slots=True)
class ArenaProgram:
    """Immutable child-before-parent node table and selected root."""

    kinds: tuple[NodeKind, ...]
    left: tuple[NodeId, ...]
    right: tuple[NodeId, ...]
    payload: tuple[object, ...]
    channel_masks: tuple[int, ...]
    channels: tuple[Channel, ...]
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
        "_left",
        "_payload",
        "_right",
    )

    def __init__(self) -> None:
        self._kinds: list[NodeKind] = []
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

    def atomic(self, operation: AtomicMorphism) -> NodeId:
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
        return self._append(
            NodeKind.WAIT,
            -1,
            -1,
            time_to_cycles(duration),
            0,
        )

    def serial(
        self,
        left: NodeId,
        right: NodeId,
        *,
        strict: bool = False,
    ) -> NodeId:
        self._validate_children(left, right)
        kind = NodeKind.STRICT_SERIAL if strict else NodeKind.AUTO_SERIAL
        return self._append(
            kind,
            left,
            right,
            None,
            self._channel_masks[left] | self._channel_masks[right],
        )

    def parallel(self, left: NodeId, right: NodeId) -> NodeId:
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
            None,
            self._channel_masks[left] | self._channel_masks[right],
        )

    def _validate_children(self, left: NodeId, right: NodeId) -> None:
        node_count = len(self._kinds)
        if not 0 <= left < node_count or not 0 <= right < node_count:
            raise ValueError(f"Invalid arena children ({left}, {right})")

    def freeze(self, root: NodeId) -> ArenaProgram:
        return ArenaProgram(
            kinds=tuple(self._kinds),
            left=tuple(self._left),
            right=tuple(self._right),
            payload=tuple(self._payload),
            channel_masks=tuple(self._channel_masks),
            channels=tuple(self._channels),
            root=root,
        )
