"""TTL compiler intrinsics.

These declarations provide the Python source-language API and type information.
Their semantics are implemented by the native compiler and the target profile.
"""

from ..morphism import Morphism, atomic_morphism, morphism
from ..morphism.core import compiler_intrinsic, compiler_only
from ..time_utils import Duration


@morphism
def pulse(duration: Duration) -> Morphism:
    """Emit a high pulse lasting ``duration`` seconds."""
    return set_high() >> hold(duration) >> set_low()


@atomic_morphism("catseq.hardware.ttl.initialize")
def initialize() -> Morphism:
    """Initialize a TTL channel in the low state."""
    compiler_only("catseq.hardware.ttl.initialize")


@atomic_morphism("catseq.hardware.ttl.set_high")
def set_high() -> Morphism:
    """Set a TTL channel high."""
    compiler_only("catseq.hardware.ttl.set_high")


@atomic_morphism("catseq.hardware.ttl.set_low")
def set_low() -> Morphism:
    """Set a TTL channel low."""
    compiler_only("catseq.hardware.ttl.set_low")


@compiler_intrinsic("catseq.hardware.ttl.hold")
def hold(duration: Duration) -> Morphism:
    """Move channel-local logical time without changing TTL state."""
    compiler_only("catseq.hardware.ttl.hold")


__all__ = ["hold", "initialize", "pulse", "set_high", "set_low"]
