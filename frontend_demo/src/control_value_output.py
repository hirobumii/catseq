# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #57
# ENTRY: feedback_count
# EXPECT: accept
# CONTRACT: Public source uses non-generic Control and returns its Device value separately.
# CONTRACT: The source pair lowers to internal Control<int> without exposing an IR generic.
# CONTRACT: The count retains its placed capture producer, dominance, Epoch, and readiness facts.

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, Id
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a


@kernel
def correction() -> Morphism:
    return Id() >> {correction_a: pulse(1 * us)}


@kernel
def feedback_count(threshold: int = 20) -> tuple[Control, int]:
    capture, count = detector0.measure(10 * us)
    decision = control.branch(
        count >= threshold,
        when_true=correction(),
        when_false=Id(),
        join=control.fixed_end(2 * us),
    )
    return capture >> decision, count
