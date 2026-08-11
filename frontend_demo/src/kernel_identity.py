# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #53
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: A public @kernel entry may construct a channel-bound Morphism.
# CONTRACT: Import may register the definition, but its body is compiler-only.

from catseq import kernel
from catseq.hardware.ttl import initialize, pulse
from catseq.morphism import Morphism, identity
from catseq.time_utils import us

from support.hardware_map import readout_a


@kernel
def sequence() -> Morphism:
    return identity(0) >> {readout_a: initialize() >> pulse(5 * us)}
