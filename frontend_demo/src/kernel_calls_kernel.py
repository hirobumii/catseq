# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #65
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: Compile-known scalar and Morphism-producing Kernel Functions may be called directly.
# CONTRACT: Every callee is statically resolved and contributes one correlated summary.

from catseq import kernel
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, identity
from catseq.time_utils import Duration, us

from support.hardware_map import correction_a


@kernel
def correction_width(base: Duration, doubled: bool) -> Duration:
    if doubled:
        return base * 2
    return base


@kernel
def correction(width: Duration) -> Morphism:
    return identity(0) >> {correction_a: pulse(width)}


@kernel
def sequence() -> Morphism:
    width = correction_width(1 * us, True)
    return correction(width) >> correction(1 * us)
