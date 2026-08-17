# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #65
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: Pure scalar early return remains inside one explicit ComputeFunction body.
# CONTRACT: Returning a scalar does not create an abrupt temporal Control exit.

from catseq import compute, control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import Id
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a, readout_a


@compute
def classify(count: int, low: int, high: int) -> int:
    if count < low:
        return -1
    if count > high:
        return 1
    return 0


@kernel
def sequence(low: int = 10, high: int = 30) -> Control:
    capture, count = detector0.measure(10 * us)
    classification = classify(count, low, high)
    choice = control.switch(
        classification,
        cases={
            -1: Id(),
            0: Id() >> {readout_a: pulse(2 * us)},
            1: Id() >> {correction_a: pulse(1 * us)},
        },
        default=Id(),
        join=control.fixed_end(3 * us),
    )
    return capture >> choice
