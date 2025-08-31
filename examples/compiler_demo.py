#!/usr/bin/env python3
"""
Demonstration of the Cat-SEQ to RTMQ Compiler

This script shows how to:
1. Create Cat-SEQ morphisms using the builder API
2. Compile them to executable Python functions using OASM DSL
3. Generate functions that can be used with RTMQ hardware

The compiled functions directly call OASM DSL methods, providing:
- Type checking and IDE support
- Direct execution without string generation
- Runtime validation of OASM calls
"""

from catseq.compiler import compile_morphism, create_executable_morphism
from catseq.protocols import Channel
from catseq.hardware.ttl import TTLDevice
from catseq.hardware.rwg import RWGDevice
from catseq.states.rwg import StaticWaveform, RWGActive
from catseq.morphisms import ttl, common


# Create a test RWG device class for the demo
class TestRWGDevice(RWGDevice):
    """Test RWG device for demonstration."""
    def __init__(self, name: str = "demo_rwg"):
        super().__init__(name=name, available_sbgs={0, 1, 2, 3}, max_ramping_order=3)


def demo_ttl_compilation():
    """Demonstrate TTL morphism compilation."""
    print("=== TTL Morphism Compilation Demo ===")
    
    # Create a TTL channel
    ttl0 = Channel("TTL_0", TTLDevice)
    
    # Create a pulse sequence using the builder API
    pulse_def = ttl.pulse(duration=10e-6)  # 10μs pulse
    hold_def = common.hold(duration=5e-6)   # 5μs hold
    
    # Compose sequence: pulse -> hold -> pulse
    sequence_def = pulse_def @ hold_def @ pulse_def
    concrete_morphism = sequence_def(ttl0)
    
    print(f"Original morphism duration: {concrete_morphism.duration*1e6:.3f} μs")
    print(f"Number of lanes: {len(concrete_morphism.lanes)}")
    
    # Compile to executable CompiledMorphism
    compiled = compile_morphism(concrete_morphism)
    
    print("Compiled morphism:")
    print(f"  - Duration: {compiled.duration*1e6:.3f} μs") 
    print(f"  - Channels: {[ch.name for ch in compiled.channels]}")
    print(f"  - Callable: {callable(compiled)}")
    
    # Create executable function for use with rwg_play()
    executable = create_executable_morphism(concrete_morphism, "ttl_pulse_sequence")
    
    print("Executable function:")
    print(f"  - Name: {executable.__name__}")
    print(f"  - Callable: {callable(executable)}")
    print(f"  - Doc: {executable.__doc__}")
    
    print("Usage pattern: rwg0_play(ttl_pulse_sequence)()")
    print()


def demo_rwg_compilation():
    """Demonstrate RWG morphism compilation."""
    print("=== RWG Morphism Compilation Demo ===")
    
    # Create an RWG channel
    rwg0 = Channel("RWG_0", TestRWGDevice)
    
    # Create an RWG waveform configuration
    waveform = StaticWaveform(sbg_id=0, freq=10.0, amp=0.5, phase=0.0)
    rwg_active_state = RWGActive(waveforms=(waveform,), carrier_freq=100.0)
    
    # Use the RWG morphism builder (create a simple active state)
    from catseq.model import PrimitiveMorphism, LaneMorphism
    from catseq.states.rwg import RWGReady
    
    rwg_pulse = PrimitiveMorphism(
        name="RWG_Tone",
        dom=((rwg0, RWGReady()),),
        cod=((rwg0, rwg_active_state),),
        duration=1e-3  # 1ms tone
    )
    
    morphism = LaneMorphism.from_primitive(rwg_pulse)
    
    print(f"RWG morphism duration: {morphism.duration*1000:.3f} ms")
    print(f"Carrier frequency: {rwg_active_state.carrier_freq} MHz")
    print(f"SBG waveform: freq={waveform.freq}MHz, amp={waveform.amp}")
    
    # Compile to executable
    compiled = compile_morphism(morphism)
    
    print("Compiled RWG morphism:")
    print(f"  - Duration: {compiled.duration*1000:.3f} ms")
    print(f"  - Channels: {[ch.name for ch in compiled.channels]}")
    
    # Create executable function
    executable = create_executable_morphism(morphism, "rwg_tone")
    
    print(f"Executable RWG function: {executable.__name__}")
    print("Usage pattern: rwg0_play(rwg_tone)()")
    print()


def demo_parallel_compilation():
    """Demonstrate parallel morphism compilation."""
    print("=== Parallel Morphism Compilation Demo ===")
    
    # Create multiple TTL channels
    ttl1 = Channel("TTL_1", TTLDevice)
    ttl2 = Channel("TTL_2", TTLDevice)
    
    # Create two different pulse sequences
    short_pulse = ttl.pulse(duration=5e-6)(ttl1)   # 5μs pulse on TTL_1
    long_pulse = ttl.pulse(duration=15e-6)(ttl2)   # 15μs pulse on TTL_2
    
    # Combine in parallel (| operator)
    parallel_morphism = short_pulse | long_pulse
    
    print("Parallel morphism:")
    print(f"  - Duration: {parallel_morphism.duration*1e6:.3f} μs (synchronized)")
    print(f"  - Lanes: {len(parallel_morphism.lanes)}")
    print(f"  - Channels: {[ch.name for ch in parallel_morphism.lanes.keys()]}")
    
    # Compile parallel morphism
    compiled = compile_morphism(parallel_morphism)
    
    print("Compiled parallel morphism:")
    print(f"  - Channels: {[ch.name for ch in compiled.channels]}")
    print(f"  - Operations are synchronized to {compiled.duration*1e6:.3f} μs")
    
    # Create executable
    executable = create_executable_morphism(parallel_morphism, "parallel_pulses")
    print(f"Executable: {executable.__name__}")
    print()


def main():
    """Run all compilation demos."""
    print("Cat-SEQ RTMQ Compiler Demonstration")
    print("===================================")
    print()
    
    demo_ttl_compilation()
    demo_rwg_compilation()
    demo_parallel_compilation()
    
    print("Key Benefits of the Python Object Approach:")
    print("- Direct OASM DSL function calls (no string generation)")
    print("- Python type checking and IDE support")
    print("- Runtime validation of OASM calls")
    print("- Executable functions compatible with rwg_play() patterns")
    print("- Better error handling and debugging")


if __name__ == "__main__":
    main()