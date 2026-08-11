# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #52
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: Reachability from a kernel does not implicitly compile an ordinary function.
# DIAGNOSTIC: host_delay must be decorated with @kernel

from catseq import kernel
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, identity
from catseq.time_utils import us

from support.hardware_map import correction_a


def host_delay() -> Morphism:
    return identity(0) >> {correction_a: pulse(1 * us)}


@kernel
def sequence() -> Morphism:
    return host_delay()
