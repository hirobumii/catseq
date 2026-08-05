"""Source intrinsic for composing CatSeq timelines with raw OASM callbacks.

The native compiler parses calls in this module without executing them. Host
callables remain outside the native Morphism arena and are resolved only by the
Python OASM assembly adapter.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .morphism import Morphism
from .morphism.core import compiler_only
from .types import Board


def black_box(
    duration_cycles: int,
    board_funcs: Mapping[Board, Callable[..., Any]],
    user_args: tuple[object, ...] = (),
    user_kwargs: Mapping[str, object] | None = None,
    metadata: Mapping[str, object] | None = None,
) -> Morphism:
    """Declare an exact-duration region encoded by downstream OASM callbacks.

    The arguments are consumed by the native compiler. Calling this function
    directly under CPython is an error, like other CatSeq source intrinsics.
    The callback map defines the participating boards; black boxes deliberately
    make no channel-state declaration or state guarantee to CatSeq.
    """

    del duration_cycles, board_funcs, user_args, user_kwargs, metadata
    compiler_only("catseq.oasm.black_box")


__all__ = ["black_box"]
