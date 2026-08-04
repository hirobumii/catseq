"""Compiler intrinsics shared by all hardware targets.

The functions in this module are part of the CatSeq source language.  They are
parsed by ``catseqc`` and must not be evaluated by the Python host runtime.
"""

from ..morphism import MorphismDef
from ..morphism.core import compiler_only
from ..time_utils import Duration


def hold(duration: Duration) -> MorphismDef:
    """Wait for ``duration`` seconds without changing channel state."""
    compiler_only("catseq.hardware.common.hold")


__all__ = ["hold"]
