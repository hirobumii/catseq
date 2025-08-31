#!/usr/bin/env python3
"""
RWG Initialize Demo - Type-Based Morphism Translation

This script demonstrates the new type-based morphism translation system
for RWG initialization, showing how rwg.initialize() is properly compiled
to RTMQ DSL based on morphism state transitions rather than string matching.
"""

from catseq.compiler import compile_morphism, create_executable_morphism
from catseq.protocols import Channel
from catseq.hardware.rwg import RWGDevice
from catseq.morphisms import rwg
from catseq.states.rwg import RWGReady


class DemoRWGDevice(RWGDevice):
    """Demo RWG device for testing."""
    def __init__(self, name: str = "demo_rwg"):
        super().__init__(name=name, available_sbgs={0, 1, 2, 3}, max_ramping_order=3)


def demo_type_based_initialize():
    """Demonstrate type-based detection of RWG initialize morphism."""
    print("=== Type-Based RWG Initialize Demo ===")
    
    # Create RWG channel
    rwg0 = Channel("RWG_0", DemoRWGDevice)
    
    print("1. Creating RWG initialize morphism:")
    print("   rwg.initialize(carrier_freq=100.0, duration=1e-6)")
    
    # Create initialize morphism
    init_morphism = rwg.initialize(carrier_freq=100.0, duration=1e-6)(rwg0)
    
    print(f"   Created morphism with duration: {init_morphism.duration*1e6:.3f} μs")
    
    # Examine the morphism structure
    lanes = init_morphism.lanes
    print(f"   Number of lanes: {len(lanes)}")
    
    for channel, primitives in lanes.items():
        print(f"   Channel {channel.name}:")
        for i, primitive in enumerate(primitives):
            from_state = primitive.dom[0][1]
            to_state = primitive.cod[0][1]
            print(f"     {i+1}. {primitive.name}")
            print(f"        From: {type(from_state).__name__}")
            print(f"        To: {type(to_state).__name__}")
            if isinstance(to_state, RWGReady):
                print(f"        Carrier freq: {to_state.carrier_freq} MHz")
    
    print("\n2. Compiling with type-based translation:")
    compiled = compile_morphism(init_morphism)
    
    print("   Compiled successfully!")
    print(f"   Duration: {compiled.duration*1e6:.3f} μs")
    print(f"   Channels: {[ch.name for ch in compiled.channels]}")
    print(f"   Callable: {callable(compiled)}")
    
    print("\n3. Type-based translation logic:")
    print("   Compiler detects: Uninitialized -> RWGReady")
    print("   This triggers complete RTMQ initialization sequence:")
    print("   - rsm.on(spi=1)")
    print("   - pdm.source(1, 1, 1, 1)")
    print("   - Configure CDS mux")
    print("   - rwg.rst_cic(0xF)")
    print("   - rwg.carrier(0xF, 100.0, upd=True)")
    print("   - rwg.timer(5000, wait=False)")
    
    return compiled


def demo_initialize_vs_waveform():
    """Compare initialization vs waveform morphism compilation."""
    print("\n=== Initialize vs Waveform Morphism Comparison ===")
    
    rwg0 = Channel("RWG_0", DemoRWGDevice)
    
    # 1. Initialize morphism
    print("1. Initialize morphism (Uninitialized -> RWGReady):")
    init_morphism = rwg.initialize(carrier_freq=100.0, duration=1e-6)(rwg0)
    init_compiled = compile_morphism(init_morphism)
    
    # 2. Create a properly sequenced waveform morphism
    print("2. Waveform playback morphism (RWGReady -> RWGActive):")
    print("   (Must be composed after initialize to have proper starting state)")
    
    # Create a complete sequence: initialize -> play
    from catseq.states.rwg import WaveformParams
    waveform_params = WaveformParams(
        sbg_id=0,
        freq_coeffs=(10.0, 0, None, None),
        amp_coeffs=(0.5, 0, None, None)
    )
    
    # Compose: init -> play 
    init_def = rwg.initialize(carrier_freq=100.0, duration=1e-6)
    play_def = rwg.play(duration=100e-6, params=(waveform_params,))
    sequence_def = init_def @ play_def
    sequence_morphism = sequence_def(rwg0)
    
    sequence_compiled = compile_morphism(sequence_morphism)
    
    print("\nComparison:")
    print(f"Initialize only - Duration: {init_compiled.duration*1e6:.3f} μs")
    print(f"Full sequence   - Duration: {sequence_compiled.duration*1e6:.3f} μs")
    
    print("\nBoth are properly compiled based on state transition types,")
    print("not string matching!")
    
    return init_compiled, sequence_compiled


def demo_complete_sequence():
    """Demonstrate complete RWG sequence: initialize + waveform."""
    print("\n=== Complete RWG Sequence Demo ===")
    
    rwg0 = Channel("RWG_0", DemoRWGDevice)
    
    # Build complete sequence: initialize -> play waveform
    init_def = rwg.initialize(carrier_freq=100.0, duration=1e-6)
    
    # Create a linear ramp
    ramp_def = rwg.linear_ramp(
        duration=50e-6,
        end_freq=20.0,
        end_amp=0.8,
        sbg_id=0
    )
    
    # Compose sequence
    sequence_def = init_def @ ramp_def
    sequence_morphism = sequence_def(rwg0)
    
    print(f"Complete sequence duration: {sequence_morphism.duration*1e6:.3f} μs")
    
    # Compile the complete sequence
    compiled_sequence = compile_morphism(sequence_morphism)
    
    print("Compiled sequence:")
    print(f"  Duration: {compiled_sequence.duration*1e6:.3f} μs")
    print(f"  Channels: {[ch.name for ch in compiled_sequence.channels]}")
    
    # Create executable function
    executable = create_executable_morphism(sequence_morphism, "rwg_init_and_ramp")
    print(f"  Executable: {executable.__name__}")
    print("  Usage: rwg0_play(rwg_init_and_ramp)()")
    
    return compiled_sequence, executable


def demo_parallel_rwg_operations():
    """Demonstrate parallel RWG operations on multiple channels."""
    print("\n=== Parallel RWG Operations Demo ===")
    
    # Create multiple RWG channels
    rwg0 = Channel("RWG_0", DemoRWGDevice)
    rwg1 = Channel("RWG_1", DemoRWGDevice)
    
    # Initialize both channels in parallel
    init0 = rwg.initialize(carrier_freq=100.0, duration=1e-6)(rwg0)
    init1 = rwg.initialize(carrier_freq=200.0, duration=1e-6)(rwg1)
    
    parallel_init = init0 | init1
    
    print("Parallel initialization:")
    print(f"  Duration: {parallel_init.duration*1e6:.3f} μs")
    print(f"  Channels: {len(parallel_init.lanes)}")
    
    # Compile parallel operations
    compiled_parallel = compile_morphism(parallel_init)
    
    print("Compiled parallel morphism:")
    print(f"  Channels: {[ch.name for ch in compiled_parallel.channels]}")
    print("  Both initialize morphisms detected by state transitions")
    
    return compiled_parallel


def main():
    """Run all demonstrations."""
    print("Cat-SEQ RWG Initialize - Type-Based Translation Demo")
    print("=" * 60)
    
    # Basic initialize demo
    compiled_init = demo_type_based_initialize()
    
    # Compare different morphism types
    init_compiled, sequence_compiled_alt = demo_initialize_vs_waveform()
    print(init_compiled.morphism)
    
    # Complete sequence demo
    sequence_compiled, sequence_executable = demo_complete_sequence()
    
    # Parallel operations demo
    parallel_compiled = demo_parallel_rwg_operations()
    
    print("\n" + "=" * 60)
    print("Key Benefits of Type-Based Translation:")
    print("✓ No string matching - uses actual morphism state transitions")
    print("✓ Type-safe morphism detection")
    print("✓ Proper separation of initialize vs waveform operations")
    print("✓ Extensible for new morphism types")
    print("✓ Better error detection and validation")
    
    print(f"\nCreated {4} compiled morphisms demonstrating type-based translation!")


if __name__ == "__main__":
    main()