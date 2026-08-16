# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #62
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: Ordinary | cannot hide dynamic completion or a runtime barrier policy.
# DIAGNOSTIC: Control operand is not SameEpochExactNormal; use control.parallel_control with a join

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import Id, Wait
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a, trigger_b


@kernel
def sequence(threshold: int = 20) -> Control:
    capture, count = detector0.measure(10 * us)
    dynamic_feedback = capture >> control.branch(
        count >= threshold,
        when_true=Id() >> {correction_a: pulse(7 * us)},
        when_false=Wait(1 * us),
        join=control.completion_token(),
    )
    independent_lane = Id() >> {trigger_b: pulse(20 * us)}
    return dynamic_feedback | independent_lane
