# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #48
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: A concrete Compile-known count controls a supported builtins.range loop.
# CONTRACT: It produces finite MorphismPower/composition, never runtime Control.

from catseq import kernel
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, Id
from catseq.time_utils import us

from support.hardware_map import correction_a


@kernel
def sequence(repetitions: int = 4) -> Morphism:
    result = Id()
    for _ in range(repetitions):
        result = result >> {correction_a: pulse(1 * us)}
    return result
