# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #58
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: switch is an ordered, finite Choice over statically declared cases.
# CONTRACT: Runtime selector values traverse existing edges and never create topology.
# CONTRACT: default participates in the same whole-region fixed_end contract.

from catseq import control, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, Id
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a, readout_a, trigger_b


@kernel
def local_correction() -> Morphism:
    return Id() >> {correction_a: pulse(1 * us)}


@kernel
def remote_correction() -> Morphism:
    return Id() >> {trigger_b: pulse(2 * us)}


@kernel
def readout_only() -> Morphism:
    return Id() >> {readout_a: pulse(3 * us)}


@kernel
def sequence() -> Control:
    capture, count = detector0.measure(10 * us)
    mode = count % 3
    choice = control.switch(
        mode,
        cases={
            0: local_correction(),
            1: remote_correction(),
            2: readout_only(),
        },
        default=Id(),
        join=control.fixed_end(4 * us),
    )
    return capture >> choice
