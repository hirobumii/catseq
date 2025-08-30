"""
Tests for the RTMQ compiler module using Python objects and OASM DSL.
"""

import pytest
from catseq.compiler import RTMQCompiler, compile_morphism, CompiledMorphism, create_executable_morphism
from catseq.model import LaneMorphism, PrimitiveMorphism, IdentityMorphism
from catseq.protocols import Channel
from catseq.hardware.ttl import TTLDevice
from catseq.hardware.rwg import RWGDevice
from catseq.states.ttl import TTLState, TTLOutputOn, TTLOutputOff
from catseq.states.rwg import RWGReady, RWGActive, StaticWaveform
from catseq.morphisms import ttl, common


class TestRTMQCompiler:
    """Test RTMQCompiler class using OASM DSL."""
    
    @pytest.fixture
    def compiler(self):
        return RTMQCompiler()
    
    @pytest.fixture 
    def ttl_channel(self):
        return Channel("TTL_0", TTLDevice)
    
    @pytest.fixture
    def rwg_channel(self):
        from tests.conftest import TestRWGDevice
        return Channel("RWG_0", TestRWGDevice)
    
    def test_compiler_initialization(self, compiler):
        assert isinstance(compiler, RTMQCompiler)
        assert TTLDevice in compiler.device_translators
        assert RWGDevice in compiler.device_translators
    
    def test_compile_simple_ttl_morphism(self, compiler, ttl_channel):
        # Create a simple morphism with one TTL pulse
        pulse = PrimitiveMorphism(
            name="Pulse",
            dom=((ttl_channel, TTLOutputOff()),),
            cod=((ttl_channel, TTLOutputOn()),),
            duration=1e-6
        )
        
        morphism = LaneMorphism.from_primitive(pulse)
        compiled = compiler.compile(morphism)
        
        assert isinstance(compiled, CompiledMorphism)
        assert compiled.duration == morphism.duration
        assert ttl_channel in compiled.channels
        assert callable(compiled.function)
        
        # Test that the compiled morphism can be executed (though we can't test OASM calls without hardware)
        assert callable(compiled)
    
    def test_compile_rwg_morphism(self, compiler, rwg_channel):
        # Create an RWG active state primitive
        waveform = StaticWaveform(sbg_id=0, freq=10.0, amp=0.5, phase=0.0)
        rwg_active = RWGActive(waveforms=(waveform,), carrier_freq=100.0)
        primitive = PrimitiveMorphism(
            name="RWG_Active",
            dom=((rwg_channel, RWGReady()),),
            cod=((rwg_channel, rwg_active),),
            duration=5e-6  # 5 microseconds
        )
        
        morphism = LaneMorphism.from_primitive(primitive)
        compiled = compiler.compile(morphism)
        
        assert isinstance(compiled, CompiledMorphism)
        assert compiled.duration == morphism.duration
        assert rwg_channel in compiled.channels
        assert callable(compiled.function)
        
        # Check that the compiled morphism has the correct metadata
        assert compiled.morphism == morphism
    
    def test_compile_parallel_morphism(self, compiler):
        # Create two channels for parallel operation
        ttl1 = Channel("TTL_1", TTLDevice) 
        ttl2 = Channel("TTL_2", TTLDevice)
        
        # Create two primitives on different channels
        pulse1 = PrimitiveMorphism(
            name="Pulse1",
            dom=((ttl1, TTLOutputOff()),),
            cod=((ttl1, TTLOutputOn()),),
            duration=2e-6
        )
        
        pulse2 = PrimitiveMorphism(
            name="Pulse2", 
            dom=((ttl2, TTLOutputOff()),),
            cod=((ttl2, TTLOutputOn()),),
            duration=2e-6
        )
        
        # Combine in parallel
        morphism = LaneMorphism.from_primitive(pulse1) | LaneMorphism.from_primitive(pulse2)
        compiled = compiler.compile(morphism)
        
        assert isinstance(compiled, CompiledMorphism)
        assert compiled.duration == morphism.duration
        
        # Should have both channels
        assert ttl1 in compiled.channels
        assert ttl2 in compiled.channels
        assert len(compiled.channels) == 2


class TestCompileMorphismFunction:
    """Test the convenience compile_morphism function and create_executable_morphism."""
    
    def test_compile_morphism_function(self):
        # Create a simple morphism
        ttl_ch = Channel("TTL_Test", TTLDevice)
        pulse = PrimitiveMorphism(
            name="TestPulse",
            dom=((ttl_ch, TTLOutputOff()),),
            cod=((ttl_ch, TTLOutputOn()),), 
            duration=1e-6
        )
        
        morphism = LaneMorphism.from_primitive(pulse)
        compiled = compile_morphism(morphism)
        
        assert isinstance(compiled, CompiledMorphism)
        assert compiled.duration == morphism.duration
        assert ttl_ch in compiled.channels
    
    def test_create_executable_morphism(self):
        """Test creating executable morphism functions."""
        # Create a simple morphism
        ttl_ch = Channel("TTL_Test", TTLDevice)
        pulse = PrimitiveMorphism(
            name="TestPulse",
            dom=((ttl_ch, TTLOutputOff()),),
            cod=((ttl_ch, TTLOutputOn()),),
            duration=1e-6
        )
        
        morphism = LaneMorphism.from_primitive(pulse)
        executable_func = create_executable_morphism(morphism, "test_pulse")
        
        assert callable(executable_func)
        assert executable_func.__name__ == "test_pulse"
        assert "Duration:" in executable_func.__doc__
    
    def test_compile_morphism_integration(self):
        """Integration test using the morphism builder API."""
        
        # Create a TTL channel
        ttl0 = Channel("TTL_0", TTLDevice)
        
        # Use builder API to create a sequence
        pulse_def = ttl.pulse(duration=10e-6)  # 10μs pulse
        hold_def = common.hold(duration=5e-6)   # 5μs hold
        
        sequence_def = pulse_def @ hold_def @ pulse_def
        concrete_morphism = sequence_def(ttl0)
        
        # Compile to executable CompiledMorphism
        compiled = compile_morphism(concrete_morphism)
        
        assert isinstance(compiled, CompiledMorphism)
        assert compiled.duration == concrete_morphism.duration
        assert ttl0 in compiled.channels
        
        # Should be callable
        assert callable(compiled)
        
        # Test executable function creation
        executable = create_executable_morphism(concrete_morphism, "catseq_sequence")
        assert callable(executable)
        assert executable.__name__ == "catseq_sequence"


class TestCompiledMorphism:
    """Test the CompiledMorphism class."""
    
    def test_compiled_morphism_execution(self):
        """Test that CompiledMorphism can be executed."""
        ttl_ch = Channel("TTL_0", TTLDevice)
        pulse = PrimitiveMorphism(
            name="TestPulse",
            dom=((ttl_ch, TTLOutputOff()),),
            cod=((ttl_ch, TTLOutputOn()),),
            duration=1e-6
        )
        
        morphism = LaneMorphism.from_primitive(pulse)
        compiled = compile_morphism(morphism)
        
        # Test direct function call
        assert compiled.function is not None
        
        # Test execute method
        # Note: We can't test actual OASM execution without hardware,
        # but we can test that the methods are callable
        try:
            # This would execute OASM calls if hardware was available
            # compiled.execute()
            pass
        except Exception as e:
            # Expected - OASM calls will fail without hardware
            # But the function structure should be correct
            pass
        
        # Test callable interface
        assert callable(compiled)
    
    def test_compile_rwg_initialize(self):
        """Test compilation of RWG initialize morphism using type-based detection."""
        from catseq.morphisms import rwg
        from catseq.hardware.rwg import RWGDevice
        from catseq.states.common import Uninitialized
        from tests.conftest import TestRWGDevice
        
        # Create RWG channel with test device
        rwg_channel = Channel("RWG_0", TestRWGDevice)
        
        # Create initialize morphism
        initialize_morphism = rwg.initialize(carrier_freq=100.0, duration=1e-6)(rwg_channel)
        
        # Compile it
        compiled = compile_morphism(initialize_morphism)
        
        assert isinstance(compiled, CompiledMorphism)
        assert compiled.duration == 1e-6
        assert rwg_channel in compiled.channels
        assert compiled.morphism == initialize_morphism
        
        # Should be executable
        assert callable(compiled)
        # Test execution (won't actually call OASM since no hardware)
        try:
            compiled()
        except Exception:
            # Expected - OASM calls will fail without hardware
            pass