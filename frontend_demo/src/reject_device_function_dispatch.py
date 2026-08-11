# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #65
# ENTRY: sequence
# EXPECT: reject
# CONTRACT: A Device value cannot choose a Kernel Function target.
# DIAGNOSTIC: Device-time function dispatch is not supported; use explicit Choice

from catseq import kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, identity
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a, readout_a


@kernel
def correction() -> Morphism:
    return identity(0) >> {correction_a: pulse(1 * us)}


@kernel
def readout() -> Morphism:
    return identity(0) >> {readout_a: pulse(2 * us)}


@kernel
def sequence() -> Control:
    capture, count = detector0.measure(10 * us)
    selector = count >= 20
    selected = correction if selector else readout
    return capture >> selected()
