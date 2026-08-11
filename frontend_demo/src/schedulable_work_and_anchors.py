# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #54
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: RWG load and realtime scalar compute are schedulable work, not cursor moves.
# CONTRACT: Only Identity displacements and timed hardware events place rigid anchors.
# CONTRACT: Work on two boards is placed from dependencies, deadlines, WCET, and resources.

from catseq import hardware, kernel
from catseq.control import Control
from catseq.morphism import identity
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import (
    correction_waveform,
    readout_waveform,
    rwg_a,
    rwg_b,
)


@kernel
def realtime_phase_word(count: int) -> int:
    if count > 20:
        return 1 << 30
    return 0


@kernel
def sequence() -> Control:
    capture, count = detector0.measure(10 * us)
    phase_word = realtime_phase_word(count)
    loaded_a = hardware.rwg.load(rwg_a, [correction_waveform])
    loaded_b = hardware.rwg.load(rwg_b, [readout_waveform])

    # These are rigid event anchors. The compiler may place both loads and the
    # phase calculation earlier when their release/deadline contracts allow it.
    play_at_20_us = identity(20 * us) >> {
        rwg_a: hardware.rwg.play(loaded_a, phase_word=phase_word),
        rwg_b: hardware.rwg.play(loaded_b),
    }
    return capture >> play_at_20_us
