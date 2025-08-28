"""
Test module for CatSeq hardware system - comprehensive tests
"""
import pytest
from catseq.hardware import BaseHardware, TTLDevice, RWGDevice
from catseq.states import (
    TTLOn, TTLOff, TTLInput, Uninitialized,
    RWGUninitialized, RWGReady, RWGActive
)
from catseq.core.protocols import PhysicsViolationError


class TestTTLDevice:
    """Test TTL device validation"""
    
    def test_ttl_device_creation(self):
        """Test TTL device instantiation"""
        ttl = TTLDevice("TTL_0")
        assert ttl.name == "TTL_0"
        assert isinstance(ttl, BaseHardware)
    
    def test_ttl_valid_transitions(self):
        """Test valid TTL state transitions"""
        ttl = TTLDevice("TTL_0")
        
        # From uninitialized to any TTL state
        ttl.validate_transition(Uninitialized(), TTLOn())
        ttl.validate_transition(Uninitialized(), TTLOff())
        ttl.validate_transition(Uninitialized(), TTLInput())
        
        # Between TTL states
        ttl.validate_transition(TTLOn(), TTLOff())
        ttl.validate_transition(TTLOff(), TTLOn())
        ttl.validate_transition(TTLInput(), TTLOn())
        ttl.validate_transition(TTLOn(), TTLInput())
    
    def test_ttl_invalid_transitions(self):
        """Test invalid TTL state transitions"""
        ttl = TTLDevice("TTL_0")
        
        # Invalid target from uninitialized
        with pytest.raises(PhysicsViolationError):
            ttl.validate_transition(Uninitialized(), RWGActive(
                sbg_id=0, carrier_freq=5e9, freq=5e9, amp=0.5, phase=0.0, rf_enabled=True
            ))
        
        # Invalid non-TTL states
        with pytest.raises(PhysicsViolationError):
            ttl.validate_transition(RWGReady(carrier_freq=5e9), TTLOn())


class TestRWGDevice:
    """Test RWG device validation"""
    
    def test_rwg_device_creation(self):
        """Test RWG device instantiation"""
        rwg = RWGDevice("RWG_0", available_sbgs={0, 1, 2})
        assert rwg.name == "RWG_0"
        assert rwg.available_sbgs == {0, 1, 2}
        assert rwg.max_ramping_order == 3
        assert isinstance(rwg, BaseHardware)
    
    def test_rwg_valid_transitions(self):
        """Test valid RWG state transitions"""
        rwg = RWGDevice("RWG_0", available_sbgs={0, 1})
        
        # From uninitialized
        rwg.validate_transition(Uninitialized(), RWGUninitialized())
        rwg.validate_transition(Uninitialized(), RWGReady(carrier_freq=5e9))
        
        # RWG state transitions
        rwg.validate_transition(RWGUninitialized(), RWGReady(carrier_freq=5e9))
        rwg.validate_transition(RWGReady(carrier_freq=5e9), RWGActive(
            sbg_id=0, carrier_freq=5e9, freq=5e9, amp=0.5, phase=0.0, rf_enabled=True
        ))
        
        # Active to Active (same SBG)
        active1 = RWGActive(sbg_id=0, carrier_freq=5e9, freq=5e9, amp=0.5, phase=0.0, rf_enabled=True)
        active2 = RWGActive(sbg_id=0, carrier_freq=5e9, freq=5.1e9, amp=0.6, phase=1.0, rf_enabled=True)
        rwg.validate_transition(active1, active2)
    
    def test_rwg_invalid_transitions(self):
        """Test invalid RWG state transitions"""
        rwg = RWGDevice("RWG_0", available_sbgs={0, 1})
        
        # Invalid SBG change during Active->Active
        active1 = RWGActive(sbg_id=0, carrier_freq=5e9, freq=5e9, amp=0.5, phase=0.0, rf_enabled=True)
        active2 = RWGActive(sbg_id=1, carrier_freq=5e9, freq=5e9, amp=0.5, phase=0.0, rf_enabled=True)
        with pytest.raises(PhysicsViolationError):
            rwg.validate_transition(active1, active2)
        
        # Invalid target from Ready
        with pytest.raises(PhysicsViolationError):
            rwg.validate_transition(RWGReady(carrier_freq=5e9), TTLOn())
    
    def test_taylor_coefficient_validation(self):
        """Test Taylor coefficient validation"""
        rwg = RWGDevice("RWG_0", available_sbgs={0}, max_ramping_order=2, max_freq_mhz=100.0)
        
        # Valid coefficients
        rwg.validate_taylor_coefficients(
            freq_coeffs=(50.0, 10.0, None, None),
            amp_coeffs=(0.5, 0.1, None, None)
        )
        
        # Invalid: too many coefficients
        with pytest.raises(PhysicsViolationError):
            rwg.validate_taylor_coefficients(
                freq_coeffs=(50.0, 10.0, 5.0, 2.0, 1.0),  # 5 coefficients
                amp_coeffs=(0.5, 0.1, None, None)
            )
        
        # Invalid: order too high (order 3 exceeds max_order=2)
        with pytest.raises(PhysicsViolationError):
            rwg.validate_taylor_coefficients(
                freq_coeffs=(50.0, 10.0, 5.0, 2.0),  # Order 3 (F3 non-zero)
                amp_coeffs=(0.5, 0.1, None, None)    # Order 1
            )
        
        # Invalid: coefficient too large
        with pytest.raises(PhysicsViolationError):
            rwg.validate_taylor_coefficients(
                freq_coeffs=(1000.0, None, None, None),  # Exceeds max_freq_mhz=100
                amp_coeffs=(0.5, None, None, None)
            )


class TestAmplitudeLockedRWG:
    """Test RWG device with amplitude lock constraints"""
    
    def test_amplitude_locked_rwg_creation(self):
        """Test amplitude-locked RWG device creation"""
        locked_rwg = RWGDevice("LOCKED_RWG", available_sbgs={0}, amplitude_locked=True)
        assert locked_rwg.amplitude_locked is True
        assert isinstance(locked_rwg, BaseHardware)
    
    def test_amplitude_lock_constraint(self):
        """Test amplitude lock constraint validation"""
        locked_rwg = RWGDevice("LOCKED_RWG", available_sbgs={0}, amplitude_locked=True)
        
        # Valid: only A0 coefficient
        locked_rwg.validate_taylor_coefficients(
            freq_coeffs=(50.0, 10.0, 5.0, None),  # Frequency ramping allowed
            amp_coeffs=(0.5, None, None, None)    # Only A0 allowed
        )
        
        # Invalid: amplitude modulation (A1 non-zero)
        with pytest.raises(PhysicsViolationError):
            locked_rwg.validate_taylor_coefficients(
                freq_coeffs=(50.0, 10.0, None, None),
                amp_coeffs=(0.5, 0.1, None, None)  # A1 violates amplitude lock
            )
        
        # Invalid: amplitude modulation (A2 non-zero)  
        with pytest.raises(PhysicsViolationError):
            locked_rwg.validate_taylor_coefficients(
                freq_coeffs=(50.0, None, None, None),
                amp_coeffs=(0.5, None, 0.05, None)  # A2 violates amplitude lock
            )
    
    def test_normal_rwg_allows_amplitude_modulation(self):
        """Test that normal RWG allows amplitude modulation"""
        normal_rwg = RWGDevice("NORMAL_RWG", available_sbgs={0}, amplitude_locked=False)
        
        # Should allow amplitude modulation
        normal_rwg.validate_taylor_coefficients(
            freq_coeffs=(50.0, 10.0, None, None),
            amp_coeffs=(0.5, 0.1, 0.05, None)  # A1, A2 allowed
        )


class TestHardwareIntegration:
    """Integration tests for hardware system"""
    
    def test_hardware_imports(self):
        """Test all hardware classes can be imported"""
        assert BaseHardware is not None
        assert TTLDevice is not None
        assert RWGDevice is not None
    
    def test_multiple_devices(self):
        """Test creating multiple different devices"""
        ttl = TTLDevice("TTL_0")
        rwg = RWGDevice("RWG_0", available_sbgs={0, 1})
        locked_rwg = RWGDevice("LOCKED_RWG", available_sbgs={2}, amplitude_locked=True)
        
        # All should have different names 
        assert ttl.name != rwg.name != locked_rwg.name
        
        # TTL and RWG should have different types, but both RWGs are same type
        assert type(ttl) != type(rwg)
        assert type(rwg) == type(locked_rwg)  # Both are RWGDevice
        
        # But all should be hardware devices
        assert isinstance(ttl, BaseHardware)
        assert isinstance(rwg, BaseHardware)
        assert isinstance(locked_rwg, BaseHardware)
        
        # Check amplitude lock setting
        assert rwg.amplitude_locked is False
        assert locked_rwg.amplitude_locked is True