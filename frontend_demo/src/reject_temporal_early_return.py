# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #65
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: Native early return cannot create an implicit terminal temporal edge.
# DIAGNOSTIC: temporal early return requires an explicit typed Control exit

from catseq import kernel
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a, readout_a


@kernel
def sequence() -> Morphism:
    capture, count = detector0.measure(10 * us)
    if count > 20:
        return capture >> {correction_a: pulse(1 * us)}
    return capture >> {readout_a: pulse(5 * us)}
