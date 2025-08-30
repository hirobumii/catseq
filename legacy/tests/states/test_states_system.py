"""
Test module for CatSeq states system - comprehensive tests
"""
import pytest
from catseq.states import (
    # TTL states
    TTLState, TTLInput, TTLOn, TTLOff,
    # RWG states  
    RWGState, RWGUninitialized, RWGReady, RWGActive, WaveformParams,
    # DAC states
    DACState, DACOff, DACStatic,
    # Common states
    Uninitialized
)


class TestTTLStates:
    """Test TTL state classes"""
    
    def test_ttl_inheritance(self):
        """Test TTL state inheritance hierarchy"""
        assert issubclass(TTLInput, TTLState)
        assert issubclass(TTLOn, TTLState)
        assert issubclass(TTLOff, TTLState)
    
    def test_ttl_instances(self):
        """Test TTL state instantiation"""
        input_state = TTLInput()
        on_state = TTLOn()
        off_state = TTLOff()
        
        assert isinstance(input_state, TTLState)
        assert isinstance(on_state, TTLState)
        assert isinstance(off_state, TTLState)
    
    def test_ttl_immutable(self):
        """Test TTL states are immutable"""
        on_state = TTLOn()
        # Should not be able to add attributes
        with pytest.raises(AttributeError):
            on_state.new_attr = "test"


class TestRWGStates:
    """Test RWG state classes"""
    
    def test_rwg_inheritance(self):
        """Test RWG state inheritance hierarchy"""
        assert issubclass(RWGUninitialized, RWGState)
        assert issubclass(RWGReady, RWGState)
        assert issubclass(RWGActive, RWGState)
    
    def test_rwg_uninitialized(self):
        """Test RWGUninitialized state"""
        uninit_state = RWGUninitialized()
        assert isinstance(uninit_state, RWGState)
    
    def test_rwg_ready(self):
        """Test RWGReady state"""
        ready_state = RWGReady(carrier_freq=5e9)
        assert isinstance(ready_state, RWGState)
        assert ready_state.carrier_freq == 5e9
    
    def test_rwg_active(self):
        """Test RWGActive state with all parameters"""
        active_state = RWGActive(
            sbg_id=0,
            carrier_freq=5e9,
            freq=5.1e9,
            amp=0.5,
            phase=0.0,
            rf_enabled=True
        )
        assert isinstance(active_state, RWGState)
        assert active_state.sbg_id == 0
        assert active_state.carrier_freq == 5e9
        assert active_state.freq == 5.1e9
        assert active_state.amp == 0.5
        assert active_state.phase == 0.0
        assert active_state.rf_enabled is True
    
    def test_rwg_immutable(self):
        """Test RWG states are immutable"""
        active_state = RWGActive(
            sbg_id=0, carrier_freq=5e9, freq=5.1e9, 
            amp=0.5, phase=0.0, rf_enabled=True
        )
        # Should not be able to modify fields
        with pytest.raises(AttributeError):
            active_state.sbg_id = 1


class TestDACStates:
    """Test DAC state classes"""
    
    def test_dac_inheritance(self):
        """Test DAC state inheritance hierarchy"""
        assert issubclass(DACOff, DACState)
        assert issubclass(DACStatic, DACState)
    
    def test_dac_off(self):
        """Test DACOff state"""
        dac_off = DACOff()
        assert isinstance(dac_off, DACState)
    
    def test_dac_static(self):
        """Test DACStatic state with voltage parameter"""
        dac_static = DACStatic(voltage=1.5)
        assert isinstance(dac_static, DACState)
        assert dac_static.voltage == 1.5
    
    def test_dac_immutable(self):
        """Test DAC states are immutable"""
        dac_static = DACStatic(voltage=2.0)
        with pytest.raises(AttributeError):
            dac_static.voltage = 3.0


class TestWaveformParams:
    """Test WaveformParams class"""
    
    def test_waveform_params_creation(self):
        """Test WaveformParams instantiation"""
        waveform = WaveformParams(
            freq_coeffs=(100e6, 1e6, None, None),
            amp_coeffs=(0.5, 0.1, None, None),
            initial_phase=0.0
        )
        assert waveform.freq_coeffs == (100e6, 1e6, None, None)
        assert waveform.amp_coeffs == (0.5, 0.1, None, None)
        assert waveform.initial_phase == 0.0
    
    def test_waveform_params_immutable(self):
        """Test WaveformParams is immutable"""
        waveform = WaveformParams(
            freq_coeffs=(100e6, None, None, None),
            amp_coeffs=(0.5, None, None, None)
        )
        with pytest.raises(AttributeError):
            waveform.initial_phase = 1.0


class TestStatesIntegration:
    """Integration tests for states system"""
    
    def test_all_imports(self):
        """Test all expected states can be imported"""
        # TTL states
        assert TTLState is not None
        assert TTLInput is not None
        assert TTLOn is not None
        assert TTLOff is not None
        
        # RWG states
        assert RWGState is not None
        assert RWGUninitialized is not None
        assert RWGReady is not None
        assert RWGActive is not None
        assert WaveformParams is not None
        
        # DAC states
        assert DACState is not None
        assert DACOff is not None
        assert DACStatic is not None
        
        # Common states
        assert Uninitialized is not None
    
    def test_state_equality(self):
        """Test state equality comparisons"""
        # Same states should be equal
        on1 = TTLOn()
        on2 = TTLOn()
        assert on1 == on2
        
        # Different states should not be equal
        on_state = TTLOn()
        off_state = TTLOff()
        assert on_state != off_state
        
        # RWG states with same parameters should be equal
        rwg1 = RWGReady(carrier_freq=5e9)
        rwg2 = RWGReady(carrier_freq=5e9)
        assert rwg1 == rwg2
        
        # RWG states with different parameters should not be equal
        rwg3 = RWGReady(carrier_freq=6e9)
        assert rwg1 != rwg3
        
        # DAC states with same parameters should be equal
        dac1 = DACStatic(voltage=1.5)
        dac2 = DACStatic(voltage=1.5)
        assert dac1 == dac2
        
        # DAC states with different parameters should not be equal
        dac3 = DACStatic(voltage=2.0)
        assert dac1 != dac3