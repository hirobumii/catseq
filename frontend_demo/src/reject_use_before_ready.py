# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #57
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: Source construction order cannot substitute for temporal dominance/readiness.
# DIAGNOSTIC: count is consumed before its producing measurement is ready

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import identity
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a


@kernel
def sequence(threshold: int = 20) -> Control:
    capture, count = detector0.measure(10 * us)
    feedback = control.branch(
        count >= threshold,
        when_true=identity(0) >> {correction_a: pulse(1 * us)},
        when_false=identity(0),
        join=control.fixed_end(2 * us),
    )
    return feedback >> capture
