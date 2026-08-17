# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #66
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: Compile-known invariant repetition remains Morphism algebra.
# CONTRACT: Canonical MorphismPower is preserved until target lowering.
# CONTRACT: The target may select a hardware loop or finite unrolling.

from catseq import kernel
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, Id, repeat_morphism
from catseq.time_utils import us

from support.hardware_map import correction_a


@kernel
def sequence(repetitions: int = 8) -> Morphism:
    one_pulse = Id() >> {correction_a: pulse(1 * us)}
    return repeat_morphism(one_pulse, repetitions)
