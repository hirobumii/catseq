# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #45
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: A Compile-known default may select Morphism topology with native Python if.
# CONTRACT: Both arms are checked, but only the selected arm enters CanonicalProgram.

from catseq import kernel
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, identity
from catseq.time_utils import us

from support.hardware_map import correction_a, readout_a


@kernel
def sequence(enabled: bool = True) -> Morphism:
    result = identity(0)
    if enabled:
        result = result >> {correction_a: pulse(1 * us)}
    else:
        result = result >> {readout_a: pulse(2 * us)}
    return result >> {readout_a: pulse(5 * us)}
