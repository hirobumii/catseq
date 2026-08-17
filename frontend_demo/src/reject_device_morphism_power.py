# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #63
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: Device count cannot turn invariant MorphismPower into runtime repetition.
# DIAGNOSTIC: Device repetition requires bounded control.loop

from catseq import kernel
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, Id, repeat_morphism
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a


@kernel
def sequence() -> Morphism:
    capture, count = detector0.measure(10 * us)
    one_pulse = Id() >> {correction_a: pulse(1 * us)}
    return capture >> repeat_morphism(one_pulse, count)
