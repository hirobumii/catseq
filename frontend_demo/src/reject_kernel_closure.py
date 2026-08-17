# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #65
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: Runtime closures cannot become Kernel Functions or carry topology.
# DIAGNOSTIC: nested kernel definitions and closures are not supported

from catseq import kernel
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, Id
from catseq.time_utils import Duration, us

from support.hardware_map import correction_a


@kernel
def sequence(width: Duration = 1 * us) -> Morphism:
    @kernel
    def captured_correction() -> Morphism:
        return Id() >> {correction_a: pulse(width)}

    return captured_correction()
