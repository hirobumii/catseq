# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #64
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: A predicate produced on board A may control an arm on board B.
# CONTRACT: Frontend records transport requirements; target schedules broadcast and dispatch.
# CONTRACT: Exact fixed_end keeps all boards in the same Epoch without a runtime barrier.

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, identity
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_b, readout_a, readout_b


@kernel
def remote_correction() -> Morphism:
    return identity(0) >> {correction_b: pulse(2 * us)}


@kernel
def simultaneous_readout() -> Morphism:
    return identity(0) >> {
        readout_a: pulse(5 * us),
        readout_b: pulse(5 * us),
    }


@kernel
def sequence(threshold: int = 20) -> Control:
    capture, count = detector0.measure(10 * us)
    cross_board_feedback = control.branch(
        count >= threshold,
        when_true=remote_correction(),
        when_false=identity(0),
        join=control.fixed_end(5 * us),
    )
    return capture >> cross_board_feedback >> simultaneous_readout()
