# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #67
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: Terminal Control has no normal continuation for ordinary >>.
# DIAGNOSTIC: terminal Control cannot be followed by serial continuation

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import Id
from catseq.time_utils import us

from support.hardware_map import readout_a


@kernel
def sequence() -> Control:
    abort = control.fail("interlock open")
    readout = Id() >> {readout_a: pulse(5 * us)}
    return abort >> readout
