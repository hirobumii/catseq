"""Global synchronization compiler intrinsics."""

from ..morphism import Morphism
from ..morphism.core import compiler_intrinsic, compiler_only


@compiler_intrinsic("catseq.hardware.sync.global_sync")
def global_sync() -> Morphism:
    """Synchronize all participating boards at a compiler-visible epoch."""
    compiler_only("catseq.hardware.sync.global_sync")


__all__ = ["global_sync"]
