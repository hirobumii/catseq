# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #60
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: A statically bounded scalar-only while remains realtime ComputeCFG.
# CONTRACT: Its arithmetic cost is schedulable work, not logical cursor displacement.

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import identity
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a


@kernel
def normalize(value: int) -> int:
    steps = 0
    while value > 255 and steps < 8:
        value = value // 2
        steps = steps + 1
    return value


@kernel
def sequence(threshold: int = 20) -> Control:
    capture, count = detector0.measure(10 * us)
    normalized = normalize(count)
    decision = control.branch(
        normalized >= threshold,
        when_true=identity(0) >> {correction_a: pulse(1 * us)},
        when_false=identity(0),
        join=control.fixed_end(2 * us),
    )
    return capture >> decision
