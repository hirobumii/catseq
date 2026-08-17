# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #65
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: Kernel functions are statically resolved definitions, not first-class values.
# DIAGNOSTIC: kernel helper used as a value

from catseq import kernel
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, Id
from catseq.time_utils import us

from support.hardware_map import correction_a


@kernel
def helper() -> Morphism:
    return Id() >> {correction_a: pulse(1 * us)}


@kernel
def sequence() -> Morphism:
    callback = helper
    return callback()
