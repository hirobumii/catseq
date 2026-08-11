# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #60
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: A Morphism-producing call cannot be discarded as an ordinary expression.
# DIAGNOSTIC: Morphism result is ignored and would lose topology

from catseq import kernel
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, identity
from catseq.time_utils import us

from support.hardware_map import correction_a, readout_a


@kernel
def correction() -> Morphism:
    return identity(0) >> {correction_a: pulse(1 * us)}


@kernel
def sequence() -> Morphism:
    correction()
    return identity(0) >> {readout_a: pulse(5 * us)}
