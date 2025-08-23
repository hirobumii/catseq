# tests/hardware/test_rwg.py

"""
Test suite for the RWG hardware rules defined in `catseq/hardware/rwg.py`.

This file contains tests for the `RWGDevice` class, focusing on its
initialization, dynamics validation, and transition validation logic.
"""

import pytest
from catseq.hardware.rwg import RWGDevice
from catseq.states.rwg import (
    RWGReady, RWGStaged, RWGActive, WaveformParams, StaticWaveform
)

# --- Test `__init__` ---

def test_rwg_device_init_success():
    """Tests successful instantiation of RWGDevice."""
    try:
        RWGDevice(name="test_rwg", available_sbgs={0, 1}, max_ramping_order=1)
    except ValueError:
        pytest.fail("RWGDevice initialization failed unexpectedly.")

def test_rwg_device_init_invalid_config():
    """
    Tests that RWGDevice raises ValueError for inconsistent configuration
    (allowing ramping when hardware doesn't support it).
    """
    with pytest.raises(ValueError, match="Policy allows ramping, but hardware does not support it"):
        RWGDevice(name="bad_rwg", available_sbgs={0}, max_ramping_order=0, allow_ramping=True)

# --- Test `validate_dynamics` ---

@pytest.fixture
def rwg_device():
    """Provides a default RWGDevice for dynamics tests."""
    return RWGDevice(name="test_rwg", available_sbgs={0, 1}, max_ramping_order=1)

def test_validate_dynamics_success(rwg_device):
    """Tests that valid dynamics pass validation."""
    dynamics = (WaveformParams(sbg_id=0, freq_coeffs=(1,0,0,0), amp_coeffs=(1,0,0,0)),)
    try:
        rwg_device.validate_dynamics(dynamics)
    except TypeError:
        pytest.fail("Valid dynamics were incorrectly rejected.")

def test_validate_dynamics_duplicate_sbg(rwg_device):
    """Tests that duplicate SBG IDs are rejected."""
    dynamics = (
        WaveformParams(sbg_id=0, freq_coeffs=(1,0,0,0), amp_coeffs=(1,0,0,0)),
        WaveformParams(sbg_id=0, freq_coeffs=(2,0,0,0), amp_coeffs=(1,0,0,0)),
    )
    with pytest.raises(TypeError, match="Duplicate SBG ID"):
        rwg_device.validate_dynamics(dynamics)

def test_validate_dynamics_unavailable_sbg(rwg_device):
    """Tests that unavailable SBG IDs are rejected."""
    dynamics = (WaveformParams(sbg_id=99, freq_coeffs=(1,0,0,0), amp_coeffs=(1,0,0,0)),)
    with pytest.raises(TypeError, match="SBG ID 99 is not available"):
        rwg_device.validate_dynamics(dynamics)

def test_validate_dynamics_ramping_not_allowed(rwg_device):
    """Tests rejection of ramping when policy forbids it."""
    rwg_device.allow_ramping = False
    dynamics = (WaveformParams(sbg_id=0, freq_coeffs=(1, 1, 0, 0), amp_coeffs=(1,0,0,0)),)
    with pytest.raises(TypeError, match="Ramping is not allowed"):
        rwg_device.validate_dynamics(dynamics)

def test_validate_dynamics_order_exceeds_capability(rwg_device):
    """Tests rejection of ramping order exceeding hardware capability."""
    dynamics = (WaveformParams(sbg_id=0, freq_coeffs=(1,1,1,0), amp_coeffs=(1,0,0,0)),)
    with pytest.raises(TypeError, match="Required order is 2, but hardware only supports up to 1"):
        rwg_device.validate_dynamics(dynamics)

# --- Test `validate_transition` ---

def test_validate_transition_identical_states(rwg_device):
    """Tests that transitions between identical states are allowed."""
    state = RWGReady(carrier_freq=100)
    try:
        rwg_device.validate_transition(state, state)
    except TypeError:
        pytest.fail("Transition between identical states was incorrectly rejected.")

def test_validate_transition_different_states(rwg_device):
    """Tests that transitions between different (non-Active) states are rejected."""
    from_state = RWGReady(carrier_freq=100)
    to_state = RWGStaged(carrier_freq=100)
    with pytest.raises(TypeError, match="State mismatch during composition"):
        rwg_device.validate_transition(from_state, to_state)

def test_validate_transition_active_continuity():
    """Tests continuity enforcement between RWGActive states."""
    device = RWGDevice(name="cont_rwg", available_sbgs={0}, allow_ramping=False, enforce_continuity=True, max_freq_jump_mhz=0.1, max_amp_jump_fs=0.1)

    wf1 = StaticWaveform(sbg_id=0, freq=100, amp=0.5, phase=0)
    from_state = RWGActive(carrier_freq=300, waveforms=(wf1,))

    # --- Should Pass ---
    wf2_ok = StaticWaveform(sbg_id=0, freq=100.05, amp=0.55, phase=1)
    to_state_ok = RWGActive(carrier_freq=300, waveforms=(wf2_ok,))
    device.validate_transition(from_state, to_state_ok)

    # --- Should Fail (Freq Jump) ---
    wf2_bad_freq = StaticWaveform(sbg_id=0, freq=100.2, amp=0.5, phase=1)
    to_state_bad_freq = RWGActive(carrier_freq=300, waveforms=(wf2_bad_freq,))
    with pytest.raises(TypeError, match="Frequency jump on SBG 0"):
        device.validate_transition(from_state, to_state_bad_freq)

    # --- Should Fail (Amp Jump) ---
    wf2_bad_amp = StaticWaveform(sbg_id=0, freq=100, amp=0.7, phase=1)
    to_state_bad_amp = RWGActive(carrier_freq=300, waveforms=(wf2_bad_amp,))
    with pytest.raises(TypeError, match="Amplitude jump on SBG 0"):
        device.validate_transition(from_state, to_state_bad_amp)

    # --- Should Fail (SBG set changed) ---
    wf3 = StaticWaveform(sbg_id=1, freq=100, amp=0.5, phase=0)
    to_state_bad_sbg = RWGActive(carrier_freq=300, waveforms=(wf3,))
    with pytest.raises(TypeError, match="Active SBGs changed"):
        device.validate_transition(from_state, to_state_bad_sbg)

def test_validate_transition_active_no_continuity():
    """Tests that large jumps are allowed if continuity is not enforced."""
    device = RWGDevice(name="noncont_rwg", available_sbgs={0}, allow_ramping=False, enforce_continuity=False)
    wf1 = StaticWaveform(sbg_id=0, freq=100, amp=0.1, phase=0)
    from_state = RWGActive(carrier_freq=300, waveforms=(wf1,))
    wf2 = StaticWaveform(sbg_id=0, freq=200, amp=0.9, phase=1)
    to_state = RWGActive(carrier_freq=300, waveforms=(wf2,))

    try:
        device.validate_transition(from_state, to_state)
    except TypeError:
        pytest.fail("Transition failed unexpectedly when continuity is not enforced.")
