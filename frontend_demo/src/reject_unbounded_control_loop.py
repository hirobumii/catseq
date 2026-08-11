# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #63
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: Device-controlled temporal repetition must declare a finite bound.
# DIAGNOSTIC: runtime ControlLoop requires max_iterations or a bounded timeout

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a


@kernel
def sequence(target_count: int = 20) -> Control:
    count = control.loop_value("count", initial=0)
    capture, measured_count = detector0.measure(5 * us)
    iteration = capture >> {correction_a: pulse(1 * us)}
    loop_region, _result = control.loop(
        condition=count < target_count,
        body=iteration,
        carry={count: measured_count},
    )
    return loop_region
