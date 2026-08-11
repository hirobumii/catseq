# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #64
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: A completion token cannot be followed as if it had a static absolute exit.
# DIAGNOSTIC: dynamic completion requires explicit control.epoch_join before continuation

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import identity
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_b, readout_a


@kernel
def sequence(threshold: int = 20) -> Control:
    capture, count = detector0.measure(10 * us)
    dynamic = control.branch(
        count >= threshold,
        when_true=identity(0) >> {correction_b: pulse(7 * us)},
        when_false=identity(1 * us),
        join=control.completion_token(),
    )
    continuation = identity(0) >> {readout_a: pulse(5 * us)}
    return capture >> dynamic >> continuation
