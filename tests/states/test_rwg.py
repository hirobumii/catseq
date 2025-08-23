# tests/states/test_rwg.py

"""
Test suite for RWG states defined in `catseq/states/rwg.py`.

This file tests the data classes related to the Ramp-Waveform Generator
(RWG) states, such as:
- `RWGState`: The base state for the RWG.
- `RWGReady`, `RWGStaged`, `RWGArmed`, `RWGActive`: Specific operational states.
- `WaveformParams`, `StaticWaveform`: Data structures for waveform definitions.

Tests ensure these data classes are instantiated correctly, handle their
specific attributes properly, and are immutable. The logic within
`WaveformParams` is also tested.
"""

import pytest
import numpy as np
from dataclasses import FrozenInstanceError
from catseq.protocols import State, Dynamics
from catseq.states.rwg import (
    WaveformParams, StaticWaveform, RWGState, RWGReady, RWGStaged, RWGArmed, RWGActive
)

# --- Tests for Data Structures ---

def test_static_waveform():
    """
    Tests the StaticWaveform data class for correct instantiation and immutability.
    """
    s = StaticWaveform(sbg_id=1, freq=100.0, amp=0.5, phase=np.pi)
    assert s.sbg_id == 1
    assert s.freq == 100.0
    assert s.amp == 0.5
    assert s.phase == np.pi

    with pytest.raises(FrozenInstanceError):
        s.freq = 200.0 # type: ignore

@pytest.mark.parametrize("order,freq_coeffs,amp_coeffs", [
    (0, (10.0, 0.0, 0.0, 0.0), (0.5, 0.0, 0.0, 0.0)),
    (1, (10.0, 1.0, 0.0, 0.0), (0.5, 0.0, 0.0, 0.0)),
    (1, (10.0, 0.0, 0.0, 0.0), (0.5, -1.0, 0.0, 0.0)),
    (2, (10.0, 1.0, 2.0, 0.0), (0.5, -1.0, 0.0, 0.0)),
    (2, (10.0, 1.0, 0.0, 0.0), (0.5, -1.0, 3.0, 0.0)),
    (3, (10.0, 1.0, 2.0, 4.0), (0.5, -1.0, 3.0, 0.0)),
    (3, (10.0, 1.0, 2.0, 0.0), (0.5, -1.0, 3.0, 5.0)),
])
def test_waveform_params_ramping_order(order, freq_coeffs, amp_coeffs):
    """
    Tests the `required_ramping_order` property of WaveformParams.
    """
    params = WaveformParams(sbg_id=0, freq_coeffs=freq_coeffs, amp_coeffs=amp_coeffs)
    assert params.required_ramping_order == order
    assert params.is_dynamical == (order > 0)

def test_waveform_params_instantiation_and_immutability():
    """
    Tests basic instantiation and immutability of WaveformParams.
    """
    params = WaveformParams(
        sbg_id=2,
        freq_coeffs=(1, 2, 3, 4),
        amp_coeffs=(5, 6, 7, 8),
        initial_phase=np.pi/2,
        phase_reset=True
    )
    # The `Dynamics` protocol is for static type checking, not runtime checks.
    # We can rely on a static type checker to validate the relationship.
    assert params.sbg_id == 2
    assert params.freq_coeffs == (1, 2, 3, 4)
    assert params.initial_phase == np.pi/2

    with pytest.raises(FrozenInstanceError):
        params.sbg_id = 3 # type: ignore

# --- Tests for RWG State Classes ---

@pytest.mark.parametrize("state_class", [RWGReady, RWGStaged, RWGArmed, RWGActive])
def test_rwg_state_subclassing(state_class):
    """
    Verifies that all concrete RWG states are subclasses of RWGState and State.
    """
    assert issubclass(state_class, RWGState)
    assert issubclass(state_class, State)

def test_rwg_ready_state():
    """Tests the RWGReady state."""
    state = RWGReady(carrier_freq=300.0)
    assert state.carrier_freq == 300.0
    with pytest.raises(FrozenInstanceError):
        state.carrier_freq = 301.0 # type: ignore

def test_rwg_staged_state():
    """Tests the RWGStaged state."""
    state = RWGStaged(carrier_freq=300.0)
    assert state.carrier_freq == 300.0
    with pytest.raises(FrozenInstanceError):
        state.carrier_freq = 301.0 # type: ignore

def test_rwg_armed_and_active_states():
    """
    Tests the RWGArmed and RWGActive states, which contain waveforms.
    """
    wfs = (
        StaticWaveform(sbg_id=0, freq=1, amp=1, phase=0),
        StaticWaveform(sbg_id=1, freq=2, amp=0.5, phase=1)
    )

    armed_state = RWGArmed(carrier_freq=300.0, waveforms=wfs)
    active_state = RWGActive(carrier_freq=300.0, waveforms=wfs)

    assert armed_state.waveforms == wfs
    assert active_state.waveforms[1].amp == 0.5

    with pytest.raises(FrozenInstanceError):
        armed_state.carrier_freq = 301.0 # type: ignore

    with pytest.raises(FrozenInstanceError):
        active_state.waveforms = () # type: ignore
