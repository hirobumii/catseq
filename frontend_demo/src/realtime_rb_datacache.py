# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #65
# ENTRY: sequence
# EXPECT: accept
# CONTRACT: An inert binding stores a bounded RB primitive-gate sequence in one DataCacheView<int>.
# CONTRACT: Cache contents are runtime data and never reconstruct or specialize Control topology.
# CONTRACT: A reusable Kernel Function reads integer gate codes through a bounded ControlLoop.
# CONTRACT: One static Switch maps every validated code to a real RWG waveform Morphism.
# CONTRACT: Every gate arm starts and ends at the explicit idle waveform boundary.
# CONTRACT: Cache reads, dispatch, and loop control are schedulable work, not cursor movement.

from catseq import control, hardware, kernel
from catseq.control import Control
from catseq.hardware.data_cache import DataCacheView
from catseq.hardware.rwg import hold, initialize, rf_off, rf_on, set_state
from catseq.morphism import Morphism, Id
from catseq.time_utils import ns, us
from catseq.types import StaticWaveform

from support.hardware_map import board_a, rwg_a


GATE_I = 0
GATE_X90 = 1
GATE_X180 = 2
GATE_Y90 = 3
GATE_Y180 = 4
GATE_NEG_X90 = 5
GATE_NEG_Y90 = 6
VALID_GATE_CODES = (
    GATE_I,
    GATE_X90,
    GATE_X180,
    GATE_Y90,
    GATE_Y180,
    GATE_NEG_X90,
    GATE_NEG_Y90,
)

MAX_RB_GATES = 64
GATE_DRIVE_TIME = 100 * ns
GATE_SLOT = 1 * us

# These Compile-known descriptions are quantized before Device execution.  The
# cache contains only integer gate codes, never Python objects or waveform data.
IDLE = StaticWaveform(freq=20.0, amp=0.0, sbg_id=0, phase=None)
X90 = StaticWaveform(freq=20.0, amp=0.18, sbg_id=0, phase=0.0)
X180 = StaticWaveform(freq=20.0, amp=0.36, sbg_id=0, phase=0.0)
Y90 = StaticWaveform(freq=20.0, amp=0.18, sbg_id=0, phase=0.25)
Y180 = StaticWaveform(freq=20.0, amp=0.36, sbg_id=0, phase=0.25)
NEG_X90 = StaticWaveform(freq=20.0, amp=0.18, sbg_id=0, phase=0.5)
NEG_Y90 = StaticWaveform(freq=20.0, amp=0.18, sbg_id=0, phase=0.75)

# A host-side RB generator has already decomposed Clifford gates and appended
# the recovery operation.  This declaration is an inert bounded data binding;
# it does not write the cache while the logical timeline is running.
RB_GATE_SEQUENCE = (
    GATE_X90,
    GATE_Y90,
    GATE_NEG_Y90,
    GATE_NEG_X90,
    GATE_X180,
    GATE_Y90,
    GATE_NEG_Y90,
    GATE_X180,
)
rb_sequence: DataCacheView[int] = hardware.data_cache.store(
    board=board_a,
    values=RB_GATE_SEQUENCE,
    capacity=MAX_RB_GATES,
    allowed_values=VALID_GATE_CODES,
)


@kernel
def gate_waveform(target: StaticWaveform) -> Morphism:
    pulse = (
        set_state([target], phase_reset=True)
        >> hold(GATE_DRIVE_TIME)
        >> set_state([IDLE], phase_reset=False)
    )
    return Id() >> {rwg_a: pulse}


@kernel
def realtime_single_qubit_gate(gate_code: int) -> Control:
    return control.switch(
        gate_code,
        cases={
            GATE_I: gate_waveform(IDLE),
            GATE_X90: gate_waveform(X90),
            GATE_X180: gate_waveform(X180),
            GATE_Y90: gate_waveform(Y90),
            GATE_Y180: gate_waveform(Y180),
            GATE_NEG_X90: gate_waveform(NEG_X90),
            GATE_NEG_Y90: gate_waveform(NEG_Y90),
        },
        # The DataCache binding validates this domain.  Keep a defensive arm so
        # an independently supplied view cannot silently emit a different gate.
        default=control.fail("invalid single-qubit gate code"),
        join=control.fixed_end(GATE_SLOT),
    )


@kernel
def cached_gate(gates: DataCacheView[int], index: int) -> Control:
    return realtime_single_qubit_gate(gates[index])


@kernel
def realtime_rb(gates: DataCacheView[int]) -> Control:
    index = control.loop_value("gate_index", initial=0)
    loop_region, _result = control.loop(
        condition=index < len(gates),
        body=cached_gate(gates, index),
        carry={index: index + 1},
        max_iterations=MAX_RB_GATES,
        on_exhausted=control.complete(),
        join=control.fixed_end(MAX_RB_GATES * GATE_SLOT),
    )
    return loop_region


@kernel
def sequence() -> Control:
    prepare = Id() >> {
        rwg_a: initialize(5_000.0, hard_init=True) >> set_state([IDLE]) >> rf_on(),
    }
    shutdown = Id() >> {rwg_a: set_state([IDLE]) >> rf_off()}
    return prepare >> realtime_rb(rb_sequence) >> shutdown
