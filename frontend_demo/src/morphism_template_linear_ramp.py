# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #55
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: A reusable Morphism Template remains composable before channel binding.
# CONTRACT: Chaining set_state and linear_ramp derives required boundary facts locally.
# CONTRACT: No ambient whole-machine history is passed through the Python function.

from catseq import kernel
from catseq.hardware.rwg import initialize, linear_ramp, set_state
from catseq.morphism import Morphism, identity
from catseq.time_utils import us

from support.hardware_map import correction_waveform, readout_waveform, rwg_a


@kernel
def sequence() -> Morphism:
    waveform = (
        initialize(80.0)
        >> set_state([readout_waveform])
        >> linear_ramp([correction_waveform], 10 * us)
    )
    return identity(0) >> {rwg_a: waveform}
