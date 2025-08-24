import pytest
import numpy as np

from catseq.model import LaneMorphism
from catseq.protocols import Channel
from catseq.hardware.rwg import RWGDevice
from catseq.states.common import Uninitialized
from catseq.states.rwg import RWGReady, WaveformParams, RWGActive
from catseq.morphisms.rwg import play, initialize, linear_ramp
from catseq.pending import PENDING
from tests.conftest import TestRWGDevice

# --- Channels ---
# We use the pre-configured TestRWGDevice from the main conftest
rwg0 = Channel("RWG0", TestRWGDevice)
rwg1 = Channel("RWG1", TestRWGDevice)

def test_pgc_cooling_use_case():
    """
    A full use-case test demonstrating a multi-channel sequence involving
    a tensor product for initialization and another for a PGC cooling ramp.
    """
    # --- 1. Define the Initialization Step ---
    # This step initializes two different RWG channels to different carrier frequencies.

    # Use the new `initialize` factory to create builders
    init_rwg0_def = initialize(carrier_freq=80.0, duration=1e-6)
    init_rwg1_def = initialize(carrier_freq=90.0, duration=1e-6)

    # Execute the builders on their respective channels
    start_state = Uninitialized()
    init_rwg0_lm = init_rwg0_def(rwg0, from_state=start_state)
    init_rwg1_lm = init_rwg1_def(rwg1, from_state=start_state)

    # `initialize_all` is the tensor product of the two initializations.
    # The `|` operator ensures they happen in parallel and are synchronized.
    initialize_all = init_rwg0_lm | init_rwg1_lm

    # --- Verification for Step 1 ---
    assert isinstance(initialize_all, LaneMorphism)
    assert len(initialize_all.lanes) == 2
    assert initialize_all.duration == 1e-6
    # Check that the combined `cod` is correct
    cod_map = {ch.name: state for ch, state in initialize_all.cod}
    assert cod_map["RWG0"] == RWGReady(carrier_freq=80.0)
    assert cod_map["RWG1"] == RWGReady(carrier_freq=90.0)


    # --- 2. Define the PGC Cooling Step ---
    # This step consists of two different ramps running in parallel on the two channels.
    # We now use the high-level `linear_ramp` factory.
    # Crucially, we do NOT provide start_freq or start_amp, as these will be
    # inferred from the context provided by `initialize_all`.

    ramp_rwg0_def = linear_ramp(duration=20e-6, end_freq=20.0, end_amp=0.5, sbg_id=0)
    ramp_rwg1_def = linear_ramp(duration=20e-6, end_freq=-5.0, end_amp=0.3, sbg_id=1)

    # To create the parallel `pgc_cooling` block, we execute the builders
    # from a PENDING state. This creates concrete but context-independent morphisms.
    pending_state = RWGReady(carrier_freq=PENDING)
    ramp_rwg0_lm = ramp_rwg0_def(rwg0, from_state=pending_state)
    ramp_rwg1_lm = ramp_rwg1_def(rwg1, from_state=pending_state)

    # `pgc_cooling` is the tensor product of the two parallel ramps.
    pgc_cooling = ramp_rwg0_lm | ramp_rwg1_lm

    # --- Verification for Step 2 ---
    assert isinstance(pgc_cooling, LaneMorphism)
    assert pgc_cooling.duration == 20e-6
    # Check the final state of each ramp
    pgc_cod_map = {ch.name: state for ch, state in pgc_cooling.cod}

    state_rwg0 = pgc_cod_map["RWG0"]
    assert isinstance(state_rwg0, RWGActive) # Type narrowing for Pylance
    final_freq_rwg0 = state_rwg0.waveforms[0].freq

    state_rwg1 = pgc_cod_map["RWG1"]
    assert isinstance(state_rwg1, RWGActive) # Type narrowing for Pylance
    final_freq_rwg1 = state_rwg1.waveforms[0].freq

    assert np.isclose(final_freq_rwg0, 20.0) # 0 + 1e6 * 20e-6
    assert np.isclose(final_freq_rwg1, -5.0) # 5 + (-0.5e6) * 20e-6


    # --- 3. Compose the Full Sequence ---
    # The final sequence is the serial composition of the initialization and the cooling.
    full_sequence = initialize_all @ pgc_cooling

    # --- Final Verification ---
    assert np.isclose(full_sequence.duration, 21e-6) # 1us + 20us

    # Check final states
    final_cod_map = {ch.name: state for ch, state in full_sequence.cod}

    final_state_rwg0 = final_cod_map["RWG0"]
    assert isinstance(final_state_rwg0, RWGActive) # Type narrowing
    assert np.isclose(final_state_rwg0.waveforms[0].freq, 20.0)

    final_state_rwg1 = final_cod_map["RWG1"]
    assert isinstance(final_state_rwg1, RWGActive) # Type narrowing
    assert np.isclose(final_state_rwg1.waveforms[0].freq, -5.0)

    print("\nPGC Cooling use-case test constructed and verified successfully!")
    print(f"Final sequence: {full_sequence}")
    print(f"Final sequence duration: {full_sequence.duration*1e6:.1f} us")
