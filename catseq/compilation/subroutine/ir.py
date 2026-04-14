"""
Internal data structures for RTMQ subroutine compilation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class CompiledSubroutine:
    """Metadata for a compiled RTMQ subroutine."""

    name: str
    abi: str
    arg_count: int
    local_count: int
    recursion_bound: int | None
    emitter: Callable[[], object]
