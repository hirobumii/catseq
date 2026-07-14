"""Global synchronization compiler intrinsics."""

from ..morphism import MorphismDef
from ..morphism.core import compiler_only


def global_sync() -> MorphismDef:
    """Synchronize all participating boards at a compiler-visible epoch."""
    compiler_only("catseq.hardware.sync.global_sync")


__all__ = ["global_sync"]
