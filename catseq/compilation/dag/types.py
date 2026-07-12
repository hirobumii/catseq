"""Public result types for DAG-native compilation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..types import OASMAddress, OASMCall


@dataclass(frozen=True, slots=True)
class CompileDelta:
    revision: int
    dirty_nodes: frozenset[int]
    recompiled_boards: frozenset[OASMAddress]
    changed_boards: frozenset[OASMAddress]


@dataclass(frozen=True, slots=True)
class CompileResult:
    calls_by_board: Mapping[OASMAddress, tuple[OASMCall, ...]]
    delta: CompileDelta
