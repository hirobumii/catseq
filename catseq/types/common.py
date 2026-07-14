"""Host-visible names used by the restricted CatSeq source language."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class ChannelType(Enum):
    """Nominal hardware channel families understood by the compiler."""

    TTL = auto()
    RWG = auto()
    RSP = auto()


@dataclass(frozen=True, slots=True)
class Board:
    """Stable board handle supplied through the Compile Environment."""

    id: str

    def __str__(self) -> str:
        return self.id


@dataclass(frozen=True, slots=True)
class Channel:
    """Stable channel handle used in source-level channel bindings."""

    board: Board
    local_id: int
    channel_type: ChannelType

    def __post_init__(self) -> None:
        if self.local_id < 0:
            raise ValueError(
                f"Channel local_id must be non-negative, got {self.local_id}"
            )

    @property
    def global_id(self) -> str:
        return f"{self.board.id}_{self.channel_type.name}_{self.local_id}"

    def __str__(self) -> str:
        return self.global_id


class State:
    """Nominal base for registered hardware state types."""


class AtomicMorphism:
    """Legacy source spelling for the compiler's sealed Atomic Operation type."""


class TimedRegion(AtomicMorphism):
    """Legacy source spelling for an Atomic Operation with a timing contract."""


class BlackBoxAtomicMorphism(TimedRegion):
    """Legacy source spelling for an opaque Atomic Operation."""
