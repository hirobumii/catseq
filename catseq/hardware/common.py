"""Compiler intrinsics shared by all hardware targets.

The functions in this module are part of the CatSeq source language. They are
interpreted by the registered-source frontend and must not be evaluated by the
Python host runtime.
"""

from ..morphism import Morphism
from ..morphism.core import compiler_intrinsic, compiler_only
from ..time_utils import Duration


@compiler_intrinsic("catseq.hardware.common.hold")
def hold(duration: Duration) -> Morphism:
    """Move channel-local logical time without changing channel state."""
    compiler_only("catseq.hardware.common.hold")


__all__ = ["hold"]
