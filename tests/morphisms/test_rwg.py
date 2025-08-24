import pytest
import numpy as np
from functools import partial

from catseq.protocols import Channel
from catseq.builder import MorphismBuilder
from catseq.model import LaneMorphism
from catseq.hardware.rwg import RWGDevice
from catseq.states.rwg import (
    RWGReady,
    RWGActive,
    WaveformParams,
    StaticWaveform,
)
from catseq.morphisms.rwg import play

# --- Test Fixtures ---

@pytest.fixture
def rwg_channel():
    """A standard RWG channel for testing."""
    device_factory = partial(
        RWGDevice,
        available_sbgs={0, 1},
        max_ramping_order=3,
        enforce_continuity=True,
        max_freq_jump_mhz=1e-3
    )
    return Channel("RF1", device_factory)

@pytest.fixture
def ready_state():
    """An initialized (Ready) RWG state with a realistic carrier."""
    return RWGReady(carrier_freq=95.0)

@pytest.fixture
def const_params_sbg0():
    """A simple constant waveform for SBG 0 with a small freq offset."""
    return WaveformParams(
        sbg_id=0,
        freq_coeffs=(5.0,),
        amp_coeffs=(0.5,),
        initial_phase=np.pi / 2,
    )

# --- Test Cases ---

def test_play_returns_builder(const_params_sbg0):
    """Tests that the factory function returns a MorphismBuilder."""
    p = play(duration=1e-6, params=(const_params_sbg0,))
    assert isinstance(p, MorphismBuilder)

def test_play_from_ready_state(rwg_channel, ready_state, const_params_sbg0):
    """Tests the first transition from Ready -> Active."""
    duration = 10e-6
    sbg_freq = const_params_sbg0.freq_coeffs[0]

    play_def = play(duration=duration, params=(const_params_sbg0,))
    result_lm = play_def(rwg_channel, from_state=ready_state)

    assert isinstance(result_lm, LaneMorphism)
    cod_state = result_lm.cod[0][1]
    assert isinstance(cod_state, RWGActive)
    assert cod_state.carrier_freq == ready_state.carrier_freq

    final_wf = cod_state.waveforms[0]
    assert np.isclose(final_wf.freq, sbg_freq)
    expected_phase = (np.pi / 2 + 2 * np.pi * sbg_freq * 1e6 * duration) % (2 * np.pi)
    assert np.isclose(final_wf.phase, expected_phase)

def test_play_from_active_continuous(rwg_channel):
    """Tests a continuous Active -> Active transition, including phase."""
    duration = 5e-6
    start_phase = np.pi / 4
    d0_f, d1_f = 5.0, 0.2e6
    d0_a = 0.5
    active_state_t0 = RWGActive(
        carrier_freq=95.0,
        waveforms=(StaticWaveform(sbg_id=0, freq=d0_f, amp=d0_a, phase=start_phase),)
    )
    ramp_params = WaveformParams(
        sbg_id=0, freq_coeffs=(d0_f, d1_f), amp_coeffs=(d0_a,), phase_reset=False,
    )

    play_def = play(duration=duration, params=(ramp_params,))
    result_lm = play_def(rwg_channel, from_state=active_state_t0)
    cod_state = result_lm.cod[0][1]

    assert np.isclose(cod_state.waveforms[0].freq, 6.0)
    integral = 2 * np.pi * 1e6 * (d0_f * duration + d1_f * (duration**2) / 2.0)
    expected_phase = (start_phase + integral) % (2 * np.pi)
    assert np.isclose(cod_state.waveforms[0].phase, expected_phase)

def test_play_from_active_discontinuous_fails(rwg_channel):
    """Tests that a discontinuous Active -> Active transition raises ValueError."""
    active_state_t0 = RWGActive(
        carrier_freq=95.0,
        waveforms=(StaticWaveform(sbg_id=0, freq=5.0, amp=0.5, phase=0),)
    )
    discontinuous_params = WaveformParams(
        sbg_id=0, freq_coeffs=(10.0,), amp_coeffs=(0.5,)
    )
    play_def = play(duration=1e-6, params=(discontinuous_params,))

    with pytest.raises(ValueError, match="Frequency discontinuity"):
        play_def(rwg_channel, from_state=active_state_t0)

def test_play_composition(rwg_channel, ready_state):
    """Tests chaining two play morphisms together with @."""
    params1 = WaveformParams(sbg_id=0, freq_coeffs=(5.0,), amp_coeffs=(0.5,))
    d0_f, d2_f = 5.0, 0.1e12
    params2 = WaveformParams(
        sbg_id=0, freq_coeffs=(d0_f, 0, d2_f), amp_coeffs=(0.5,), phase_reset=False
    )

    play1_def = play(duration=10e-6, params=(params1,))
    play2_def = play(duration=5e-6, params=(params2,))
    final_lm = (play1_def @ play2_def)(rwg_channel, from_state=ready_state)

    assert final_lm.duration == pytest.approx(15e-6)
    cod_state = final_lm.cod[0][1]
    assert isinstance(cod_state, RWGActive)
    final_freq = d0_f + d2_f*(5e-6)**2/2.0
    assert np.isclose(cod_state.waveforms[0].freq, final_freq)
