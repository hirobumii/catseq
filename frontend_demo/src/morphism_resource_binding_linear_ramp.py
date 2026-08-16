# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #55
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: linear_ramp produces a Morphism with one free RWG Resource Slot.
# CONTRACT: Free-slot Morphisms remain composable before Resource Slot Binding.
# CONTRACT: Binding rwg_a preserves the Morphism sort and substitutes its slot.
# CONTRACT: The compiler infers the composite Boundary Contract from the definition body.
# CONTRACT: Serial binds linear_ramp's input snapshot from set_state's output record.
# CONTRACT: Chaining set_state and linear_ramp derives the new boundary facts locally.
# CONTRACT: No ambient whole-machine history is passed through the Python function.

from catseq import kernel
from catseq.hardware.rwg import initialize, linear_ramp, set_state
from catseq.morphism import Morphism, Id
from catseq.time_utils import us

from support.hardware_map import correction_waveform, readout_waveform, rwg_a


@kernel
def sequence() -> Morphism:
    waveform = (
        initialize(80.0)
        >> set_state([readout_waveform])
        >> linear_ramp([correction_waveform], 10 * us)
    )
    return Id() >> {rwg_a: waveform}
