# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #60
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: A reusable bounded scalar loop is declared as an explicit ComputeFunction.
# CONTRACT: It creates neither MorphismPower nor temporal ControlLoop topology.

from catseq import compute, control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import identity
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a


@compute
def filter_count(count: int) -> int:
    filtered = count
    for _ in range(4):
        filtered = (filtered * 3 + 1) // 4
    return filtered


@kernel
def sequence(threshold: int = 20) -> Control:
    capture, count = detector0.measure(10 * us)
    filtered = filter_count(count)
    decision = control.branch(
        filtered >= threshold,
        when_true=identity(0) >> {correction_a: pulse(1 * us)},
        when_false=identity(0),
        join=control.fixed_end(2 * us),
    )
    return capture >> decision
