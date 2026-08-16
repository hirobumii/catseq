# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #54
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: One exact Morphism may span channels on several logical boards.
# CONTRACT: Source stays unified; target lowering partitions and binds board fragments.

from catseq import kernel
from catseq.hardware.ttl import initialize, pulse
from catseq.morphism import Morphism, Id
from catseq.time_utils import us

from support.hardware_map import correction_a, trigger_b


@kernel
def sequence() -> Morphism:
    initialize_outputs = Id() >> {
        correction_a: initialize(),
        trigger_b: initialize(),
    }
    cross_board_pulse = Id() >> {
        correction_a: pulse(4 * us),
        trigger_b: pulse(4 * us),
    }
    return initialize_outputs >> cross_board_pulse
