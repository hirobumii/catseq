# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #80
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: Automatic ComputeRegion outlining rejects a Device float result before Kernel elaboration.
# CONTRACT: Integer true division is rejected because the pinned NAC3 semantics produce float.
# DIAGNOSTIC: Device-time float is unsupported; use integer or first-class fixed-point arithmetic

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import Id
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a


@kernel
def sequence() -> Control:
    capture, count = detector0.measure(10 * us)
    normalized = count / 100
    decision = control.branch(
        normalized > 0,
        when_true=Id() >> {correction_a: pulse(1 * us)},
        when_false=Id(),
        join=control.fixed_end(1 * us),
    )
    return capture >> decision
