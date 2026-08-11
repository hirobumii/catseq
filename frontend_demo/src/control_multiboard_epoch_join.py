# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #64
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: Variable cross-board completion explicitly rendezvouses through EpochJoin.
# CONTRACT: Participating boards are inferred from logical resource support.
# CONTRACT: Continuation starts at a new Epoch origin after bounded synchronization.

from catseq import control, hardware, kernel
from catseq.control import Control
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, identity
from catseq.time_utils import us

from support.detectors import detector0
from support.hardware_map import correction_b, readout_a, readout_b


@kernel
def remote_correction() -> Morphism:
    return identity(0) >> {correction_b: pulse(7 * us)}


@kernel
def local_noop() -> Morphism:
    return identity(1 * us)


@kernel
def next_epoch_readout() -> Morphism:
    return identity(0) >> {
        readout_a: pulse(5 * us),
        readout_b: pulse(5 * us),
    }


@kernel
def sequence(threshold: int = 20) -> Control:
    capture, count = detector0.measure(10 * us)
    adaptive = control.branch(
        count >= threshold,
        when_true=remote_correction(),
        when_false=local_noop(),
        join=control.epoch_join(
            sync_contract=hardware.sync.rtmq_rendezvous(
                timeout=20 * us,
                on_timeout="fail",
            )
        ),
    )
    return capture >> adaptive >> next_epoch_readout()
