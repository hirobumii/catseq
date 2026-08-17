# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #58
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: Measurement correlates one timed acquisition region with one int @ Device.
# CONTRACT: Device predicate selects two statically present arms through explicit Branch.
# CONTRACT: fixed_end budgets readiness, compute, dispatch, selected work, and padding.

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, Id
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a, readout_a


@kernel
def correction() -> Morphism:
    return Id() >> {correction_a: pulse(1 * us)}


@kernel
def readout() -> Morphism:
    return Id() >> {readout_a: pulse(5 * us)}


@kernel
def sequence(threshold: int = 20) -> Control:
    capture, count = detector0.measure(10 * us)
    feedback = control.branch(
        count >= threshold,
        when_true=correction(),
        when_false=Id(),
        join=control.fixed_end(2 * us),
    )
    return capture >> feedback >> readout()
