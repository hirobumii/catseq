# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #60
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: A statically bounded scalar-only while inside @kernel is completely outlined as a ComputeRegion.
# CONTRACT: Its arithmetic cost is schedulable work, not logical cursor displacement.

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import Id
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a


@kernel
def sequence(threshold: int = 20) -> Control:
    capture, count = detector0.measure(10 * us)
    normalized = count
    steps = 0
    while normalized > 255 and steps < 8:
        normalized = normalized // 2
        steps = steps + 1
    decision = control.branch(
        normalized >= threshold,
        when_true=Id() >> {correction_a: pulse(1 * us)},
        when_false=Id(),
        join=control.fixed_end(2 * us),
    )
    return capture >> decision
