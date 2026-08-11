# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #45
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: Compile-known false selects the else topology without creating Choice.
# CONTRACT: The unselected arm is still parsed, resolved, and type-checked.

from catseq import kernel
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, identity
from catseq.time_utils import us

from support.hardware_map import correction_a, readout_a


@kernel
def sequence(enabled: bool = False) -> Morphism:
    result = identity(0)
    if enabled:
        result = result >> {correction_a: pulse(1 * us)}
    else:
        result = result >> {readout_a: pulse(2 * us)}
    return result >> {readout_a: pulse(5 * us)}
