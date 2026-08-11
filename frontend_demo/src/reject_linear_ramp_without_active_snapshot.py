# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #55
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: RWG initialization provides Ready but no active waveform snapshot.
# CONTRACT: Serial cannot invent the predecessor value required by linear_ramp.
# DIAGNOSTIC: linear_ramp requires an Active boundary with a waveform snapshot

from catseq import kernel
from catseq.hardware.rwg import initialize, linear_ramp
from catseq.morphism import Morphism
from catseq.time_utils import us

from support.hardware_map import correction_waveform, rwg_a


@kernel
def sequence() -> Morphism:
    invalid_ramp = (
        initialize(80.0)
        >> linear_ramp([correction_waveform], 10 * us)
    )
    return {rwg_a: invalid_ramp}
