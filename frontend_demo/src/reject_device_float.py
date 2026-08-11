# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #54
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: RTMQ Device ComputeCFG has no floating-point values or operations.
# DIAGNOSTIC: Device-time float is unsupported; use fixed-point integer arithmetic

from catseq import control, kernel
from catseq.control import Control
from catseq.morphism import identity
from catseq.time_utils import us

from support.detectors import detector0


@kernel
def normalize(count: int) -> float:
    return float(count) / 100.0


@kernel
def sequence() -> Control:
    capture, count = detector0.measure(10 * us)
    ratio = normalize(count)
    choice = control.branch(
        ratio > 0.5,
        when_true=identity(0),
        when_false=identity(0),
        join=control.fixed_end(1 * us),
    )
    return capture >> choice
