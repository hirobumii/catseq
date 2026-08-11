# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #60
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: Native Python if/elif over Device values remains scalar ComputeCFG.
# CONTRACT: Only the explicit switch below contributes canonical Choice topology.
# CONTRACT: Ordered elif and scalar SSA merge preserve one int @ Device result.

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, identity
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a, readout_a, trigger_b


@kernel
def classify(count: int, low: int, high: int) -> int:
    if count < low:
        bucket = 0
    elif count < high:
        bucket = 1
    else:
        bucket = 2
    return bucket


@kernel
def short_readout() -> Morphism:
    return identity(0) >> {readout_a: pulse(2 * us)}


@kernel
def correction() -> Morphism:
    return identity(0) >> {correction_a: pulse(1 * us)}


@kernel
def flag_remote_board() -> Morphism:
    return identity(0) >> {trigger_b: pulse(1 * us)}


@kernel
def sequence(low: int = 10, high: int = 30) -> Control:
    capture, count = detector0.measure(10 * us)
    bucket = classify(count, low, high)
    select_readout = control.switch(
        bucket,
        cases={
            0: short_readout(),
            1: correction(),
            2: flag_remote_board(),
        },
        default=identity(0),
        join=control.fixed_end(3 * us),
    )
    return capture >> select_readout
