# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #55
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: Identity with nonzero duration moves only the logical cursor.
# CONTRACT: Rewind may place a later rigid event before the prior cursor exit.
# CONTRACT: The Morphism frontier remains the furthest rigid event reached.

from catseq import kernel
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, identity
from catseq.time_utils import us

from support.hardware_map import correction_a, readout_a


@kernel
def sequence() -> Morphism:
    correction_at_5_us = identity(5 * us) >> {
        correction_a: pulse(2 * us)
    }
    rewind_to_3_us = identity(-4 * us)
    readout_at_3_us = identity(0) >> {readout_a: pulse(1 * us)}
    return correction_at_5_us >> rewind_to_3_us >> readout_at_3_us
