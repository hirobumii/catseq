#!/usr/bin/env python3
"""
TTL Framework Complete Demo

Demonstrates the full TTL workflow using existing CatSeq framework:
1. Core system (protocols, objects, morphisms)
2. States system (TTL states)
3. Hardware system (TTL device)
4. Factory functions (TTL morphisms)
5. Complete experiment composition
"""

from catseq.core.protocols import Channel
from catseq.hardware import TTLDevice
from catseq.states import TTLOn, TTLOff, Uninitialized
from catseq.morphisms.ttl import pulse, hold_on, hold_off, initialize


def setup_experiment():
    """Set up experimental hardware channels"""
    print("=== Setting up TTL Experiment ===")
    
    # Create TTL devices
    laser_device = TTLDevice("LASER_CONTROLLER")
    detector_device = TTLDevice("DETECTOR_CONTROLLER")
    
    # Create channels bound to devices
    laser_channel = Channel("LASER_TRIGGER", laser_device)
    detector_channel = Channel("DETECTOR_GATE", detector_device)
    
    print(f"Laser channel: {laser_channel}")
    print(f"Detector channel: {detector_channel}")
    print(f"Laser device: {laser_channel.device}")
    print(f"Detector device: {detector_channel.device}")
    
    return laser_channel, detector_channel


def demonstrate_basic_operations():
    """Demonstrate basic TTL operations"""
    print("\n=== Basic TTL Operations ===")
    
    laser, detector = setup_experiment()
    
    # 1. Channel initialization
    print("\n1. Channel Initialization:")
    laser_init = initialize(laser)
    detector_init = initialize(detector)
    
    print(f"   Laser init: {laser_init}")
    print(f"   Duration: {laser_init.duration:.2e}s")
    print(f"   Operations: {len(laser_init.lanes[laser])}")
    
    # 2. Basic pulse
    print("\n2. Basic Pulse Creation:")
    laser_pulse = pulse(laser, 50e-6)  # 50μs pulse
    
    print(f"   Laser pulse: {laser_pulse}")
    print(f"   Duration: {laser_pulse.duration:.2e}s")
    print(f"   Operations: {len(laser_pulse.lanes[laser])}")
    
    # Show pulse composition details
    print("   Pulse sequence:")
    for i, op in enumerate(laser_pulse.lanes[laser]):
        print(f"     {i+1}. {op.from_state} -> {op.to_state} ({op.duration:.2e}s)")
    
    # 3. Hold operations
    print("\n3. Hold Operations:")
    hold_on_op = hold_on(detector, 100e-6)  # Hold ON for 100μs
    hold_off_op = hold_off(detector, 200e-6)  # Hold OFF for 200μs
    
    print(f"   Hold ON: {hold_on_op.duration:.2e}s")
    print(f"   Hold OFF: {hold_off_op.duration:.2e}s")
    
    return laser, detector, laser_init, detector_init, laser_pulse


def demonstrate_serial_composition():
    """Demonstrate serial morphism composition"""
    print("\n=== Serial Composition ===")
    
    laser, detector, laser_init, detector_init, laser_pulse = demonstrate_basic_operations()
    
    # Create detector pulse
    detector_pulse = pulse(detector, 75e-6)  # 75μs detector pulse
    
    print(f"\nDetector pulse: {detector_pulse}")
    print(f"Duration: {detector_pulse.duration:.2e}s")
    
    # Serial composition: laser first, then detector
    print("\nSerial composition: Laser @ Detector")
    try:
        # This should fail because laser ends in OFF, detector starts in OFF (compatible)
        # But they're on different channels, so we need parallel init first
        
        # Initialize both channels first
        init_both = laser_init | detector_init
        
        # Create sequential experiment: init -> laser -> detector
        sequential_exp = init_both @ laser_pulse @ detector_pulse
        
        print(f"Sequential experiment: {sequential_exp}")
        print(f"Total duration: {sequential_exp.duration:.2e}s")
        print(f"Channels involved: {[ch.name for ch in sequential_exp.channels]}")
        
        # Analyze the composition
        print("\nSequence breakdown:")
        print(f"1. Init both channels: {init_both.duration:.2e}s")
        print(f"2. Laser pulse: {laser_pulse.duration:.2e}s") 
        print(f"3. Detector pulse: {detector_pulse.duration:.2e}s")
        
        return sequential_exp
        
    except Exception as e:
        print(f"Composition failed: {e}")
        return None


def demonstrate_parallel_composition():
    """Demonstrate parallel morphism composition"""
    print("\n=== Parallel Composition ===")
    
    laser, detector, laser_init, detector_init, laser_pulse = demonstrate_basic_operations()
    detector_pulse = pulse(detector, 75e-6)
    
    # Parallel composition: laser | detector (simultaneous)
    print("\nParallel composition: Laser | Detector")
    try:
        # Initialize both first
        init_both = laser_init | detector_init
        
        # Run pulses in parallel
        parallel_pulses = laser_pulse | detector_pulse
        
        # Complete parallel experiment
        parallel_exp = init_both @ parallel_pulses
        
        print(f"Parallel experiment: {parallel_exp}")
        print(f"Total duration: {parallel_exp.duration:.2e}s")
        
        # Show time synchronization
        print("\nTime synchronization analysis:")
        print(f"Laser pulse duration: {laser_pulse.duration:.2e}s")
        print(f"Detector pulse duration: {detector_pulse.duration:.2e}s")
        print(f"Parallel duration: {parallel_pulses.duration:.2e}s (max of both)")
        
        # Show lane details
        print("\nLane analysis:")
        for channel, ops in parallel_exp.lanes.items():
            print(f"{channel.name}: {len(ops)} operations")
            total_dur = sum(op.duration for op in ops)
            print(f"  Total duration: {total_dur:.2e}s")
        
        return parallel_exp
        
    except Exception as e:
        print(f"Parallel composition failed: {e}")
        return None


def demonstrate_hardware_validation():
    """Demonstrate hardware constraint validation"""
    print("\n=== Hardware Validation ===")
    
    laser, detector = setup_experiment()
    
    print("1. Valid state transitions:")
    # These should work
    laser.device.validate_transition(TTLOff(), TTLOn())
    laser.device.validate_transition(TTLOn(), TTLOff())
    print("   ✅ TTL OFF -> ON: Valid")
    print("   ✅ TTL ON -> OFF: Valid")
    
    print("\n2. Invalid state transitions:")
    # This should fail
    try:
        from catseq.states import RWGReady
        laser.device.validate_transition(TTLOff(), RWGReady(carrier_freq=5e9))
        print("   ❌ Should have failed!")
    except Exception as e:
        print(f"   ✅ TTL -> RWG rejected: {type(e).__name__}")
    
    print("\n3. Device-specific constraints:")
    print(f"   Laser device name: {laser.device.name}")
    print(f"   Detector device name: {detector.device.name}")
    print(f"   Same device type: {type(laser.device) == type(detector.device)}")
    print(f"   Different instances: {laser.device is not detector.device}")


def demonstrate_complete_workflow():
    """Demonstrate complete experimental workflow"""
    print("\n" + "="*60)
    print("COMPLETE TTL FRAMEWORK DEMONSTRATION")
    print("="*60)
    
    # 1. Setup
    laser, detector = setup_experiment()
    
    # 2. Build experiment components
    print("\n--- Building Experiment Components ---")
    init_laser = initialize(laser)
    init_detector = initialize(detector)
    
    # Create more complex pulse patterns
    short_pulse = pulse(laser, 10e-6)   # 10μs
    long_pulse = pulse(laser, 100e-6)   # 100μs
    detector_gate = pulse(detector, 150e-6)  # 150μs
    
    # 3. Composition examples
    print("\n--- Composition Examples ---")
    
    # Example 1: Sequential pulses
    init_both = init_laser | init_detector
    sequential = init_both @ short_pulse @ long_pulse @ detector_gate
    
    print(f"Sequential experiment:")
    print(f"  Duration: {sequential.duration:.2e}s")
    print(f"  Channels: {len(sequential.channels)}")
    
    # Example 2: Overlapping operations
    laser_sequence = short_pulse @ long_pulse  # Two laser pulses
    parallel_exp = init_both @ (laser_sequence | detector_gate)
    
    print(f"Parallel experiment:")
    print(f"  Duration: {parallel_exp.duration:.2e}s")
    print(f"  Time saved: {sequential.duration - parallel_exp.duration:.2e}s")
    
    # 4. Validation
    print("\n--- Validation ---")
    demonstrate_hardware_validation()
    
    # 5. Analysis
    print(f"\n--- Final Analysis ---")
    print(f"Framework components used:")
    print(f"  ✅ Core protocols: Channel, SystemState") 
    print(f"  ✅ Core morphisms: Morphism, AtomicOperation")
    print(f"  ✅ States: TTLOn, TTLOff, Uninitialized")
    print(f"  ✅ Hardware: TTLDevice")
    print(f"  ✅ Factory functions: pulse, hold_on, hold_off, initialize")
    print(f"  ✅ Composition: @ (serial), | (parallel)")
    print(f"  ✅ Validation: Hardware constraints")
    
    return parallel_exp


if __name__ == "__main__":
    # Run complete demonstration
    print("Starting TTL Framework Demo...")
    
    try:
        final_experiment = demonstrate_complete_workflow()
        print(f"\n🎉 Demo completed successfully!")
        print(f"Final experiment: {final_experiment}")
        
    except Exception as e:
        print(f"\n💥 Demo failed: {e}")
        import traceback
        traceback.print_exc()