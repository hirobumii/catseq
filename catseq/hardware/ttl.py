"""TTL compiler intrinsics.

These declarations provide the Python source-language API and type information.
Their semantics are implemented by the native compiler and the target profile.
"""

from ..morphism import MorphismDef, atomic_morphism, morphism_template
from ..morphism.core import compiler_only


@morphism_template
def pulse(duration: float) -> MorphismDef:
    """Emit a high pulse lasting ``duration`` seconds."""
    return set_high() >> hold(duration) >> set_low()


@atomic_morphism("catseq.hardware.ttl.initialize")
def initialize() -> MorphismDef:
    """Initialize a TTL channel in the low state."""
    compiler_only("catseq.hardware.ttl.initialize")


@atomic_morphism("catseq.hardware.ttl.set_high")
def set_high() -> MorphismDef:
    """Set a TTL channel high."""
    compiler_only("catseq.hardware.ttl.set_high")


@atomic_morphism("catseq.hardware.ttl.set_low")
def set_low() -> MorphismDef:
    """Set a TTL channel low."""
    compiler_only("catseq.hardware.ttl.set_low")


@morphism_template
def hold(duration: float) -> MorphismDef:
    """Wait for ``duration`` seconds without changing TTL state."""
    compiler_only("catseq.hardware.ttl.hold")


__all__ = ["hold", "initialize", "pulse", "set_high", "set_low"]
