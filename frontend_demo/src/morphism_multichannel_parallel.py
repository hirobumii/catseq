# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #38
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: One Morphism may own several disjoint channels on one board.
# CONTRACT: Parallel lanes share an entry and align to the maximum frontier automatically.

from catseq import kernel
from catseq.hardware.ttl import initialize, pulse
from catseq.morphism import Morphism, Id
from catseq.time_utils import us

from support.hardware_map import correction_a, readout_a


@kernel
def sequence() -> Morphism:
    initialize_outputs = Id() >> {
        correction_a: initialize(),
        readout_a: initialize(),
    }
    simultaneous_pulses = Id() >> {
        correction_a: pulse(2 * us),
        readout_a: pulse(5 * us),
    }
    return initialize_outputs >> simultaneous_pulses
