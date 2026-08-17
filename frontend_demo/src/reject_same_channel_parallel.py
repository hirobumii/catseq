# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #38
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: Parallel Morphism lanes cannot claim the same exclusive channel.
# DIAGNOSTIC: correction_a is used by overlapping parallel lanes

from catseq import kernel
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, Id
from catseq.time_utils import us

from support.hardware_map import correction_a


@kernel
def sequence() -> Morphism:
    short = Id() >> {correction_a: pulse(1 * us)}
    long = Id() >> {correction_a: pulse(2 * us)}
    return short | long
