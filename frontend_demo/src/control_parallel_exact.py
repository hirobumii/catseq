# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #62
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: Ordinary | may mix Morphism and Control only with SameEpochExactNormal exits.
# CONTRACT: fixed_end makes the feedback lane statically alignable without a barrier.
# CONTRACT: Resource checks distinguish coexisting lanes from mutually exclusive arms.

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import identity
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a, trigger_b


@kernel
def sequence(threshold: int = 20) -> Control:
    capture, count = detector0.measure(10 * us)
    feedback_lane = capture >> control.branch(
        count >= threshold,
        when_true=identity(0) >> {correction_a: pulse(1 * us)},
        when_false=identity(0),
        join=control.fixed_end(3 * us),
    )
    independent_lane = identity(0) >> {trigger_b: pulse(13 * us)}
    return feedback_lane | independent_lane
