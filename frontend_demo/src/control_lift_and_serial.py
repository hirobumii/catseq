# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #67
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: M >> C and C >> M return Control through compiler-owned Lift.
# CONTRACT: Adjacent pure Morphism regions remain maximal Morphism islands.
# CONTRACT: Source never constructs Lift nodes or manipulates canonical topology directly.

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, identity
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a, readout_a


@kernel
def prepare() -> Morphism:
    return identity(0) >> {readout_a: pulse(2 * us)}


@kernel
def finish() -> Morphism:
    return identity(0) >> {readout_a: pulse(5 * us)}


@kernel
def sequence(threshold: int = 20) -> Control:
    capture, count = detector0.measure(10 * us)
    choice = control.branch(
        count >= threshold,
        when_true=identity(0) >> {correction_a: pulse(1 * us)},
        when_false=identity(0),
        join=control.fixed_end(2 * us),
    )
    return prepare() >> capture >> choice >> finish()
