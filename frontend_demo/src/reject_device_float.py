# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #80
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: ComputeRegion and ComputeFunction bodies have no floating-point values or operations.
# DIAGNOSTIC: Device-time float is unsupported; use integer or first-class fixed-point arithmetic

from catseq import compute, control, kernel
from catseq.control import Control
from catseq.morphism import Id
from catseq.time_utils import us

from support.detectors import detector0


@compute
def normalize(count: int) -> float:
    return float(count) / 100.0


@kernel
def sequence() -> Control:
    capture, count = detector0.measure(10 * us)
    ratio = normalize(count)
    choice = control.branch(
        ratio > 0.5,
        when_true=Id(),
        when_false=Id(),
        join=control.fixed_end(1 * us),
    )
    return capture >> choice
