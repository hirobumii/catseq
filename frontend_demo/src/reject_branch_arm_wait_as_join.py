# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #58
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: Arm-local cursor displacement is not a whole-Choice completion policy.
# DIAGNOSTIC: Branch requires an explicit join; when_false Wait is not fixed_end

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import Id, Wait
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a


@kernel
def sequence(threshold: int = 20) -> Control:
    capture, count = detector0.measure(10 * us)
    choice = control.branch(
        count >= threshold,
        when_true=Id() >> {correction_a: pulse(1 * us)},
        when_false=Wait(2 * us),
    )
    return capture >> choice
