# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #63
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: Runtime temporal repetition is a bounded ControlLoop with static body topology.
# CONTRACT: One typed Device scalar is carried through explicit initial and carry edges.
# CONTRACT: Predicate, carry, latch, timeout, and dispatch are schedulable work.
# CONTRACT: The source pair lowers to internal Control<LoopResult> after normal completion.

from catseq import control, kernel
from catseq.control import Control, LoopResult
from catseq.hardware.ttl import pulse
from catseq.morphism import Id
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_a, readout_a


@kernel
def sequence(target_count: int = 20) -> tuple[Control, LoopResult]:
    count = control.loop_value("count", initial=0)
    capture, measured_count = detector0.measure(5 * us)
    iteration = capture >> {
        correction_a: pulse(1 * us),
    }
    adaptive_capture, result = control.loop(
        condition=count < target_count,
        body=iteration,
        carry={count: measured_count},
        max_iterations=8,
        on_exhausted=control.complete(),
        join=control.fixed_end(60 * us),
    )
    final_readout = Id() >> {readout_a: pulse(5 * us)}
    return adaptive_capture >> final_readout, result
