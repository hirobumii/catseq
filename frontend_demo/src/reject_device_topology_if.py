# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #60
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: Native Python Device if cannot select or merge Morphism topology.
# DIAGNOSTIC: use control.branch for Device-selected topology

from catseq import kernel
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, Id
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a, readout_a


@kernel
def sequence(threshold: int = 20) -> Morphism:
    capture, count = detector0.measure(10 * us)
    if count >= threshold:
        result = Id() >> {correction_a: pulse(1 * us)}
    else:
        result = Id() >> {readout_a: pulse(2 * us)}
    return capture >> result
