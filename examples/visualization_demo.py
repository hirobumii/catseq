#!/usr/bin/env python3
"""
Demo script for the new functional visualization interface.
"""

from catseq.types import Board, Channel, ChannelType
from catseq.types.rwg import RWGActive, StaticWaveform
from catseq.hardware import ttl, rwg
from catseq.morphism import identity
from catseq.visualization import (
    visualize_morphism,
    plot_timeline,
    text_timeline,
    analyze_morphism_timing,
    detect_sync_points,
    detect_pulse_patterns,
)


def demo_functional_visualization():
    """Demonstrate the new functional visualization capabilities"""
    
    print("=== CatSeq Functional Visualization Demo ===\n")
    
    # Create test channels
    board = Board("RWG_0")
    ttl_ch0 = Channel(board=board, channel_type=ChannelType.TTL, local_id=0)
    ttl_ch1 = Channel(board=board, channel_type=ChannelType.TTL, local_id=1)
    rwg_ch0 = Channel(board=board, channel_type=ChannelType.RWG, local_id=0)
    
    # Demo 1: Simple TTL pulse
    print("1. Simple TTL Pulse:")
    simple_pulse = ttl.pulse(ttl_ch0, 50.0)
    print(text_timeline(simple_pulse, style='compact'))
    print()
    
    # Demo 2: Parallel operations
    print("2. Parallel TTL Operations:")
    pulse1 = ttl.pulse(ttl_ch0, 30.0)
    pulse2 = ttl.pulse(ttl_ch1, 20.0) 
    parallel = pulse1 | pulse2
    print(text_timeline(parallel, style='compact'))
    print()
    
    # Demo 3: RF pulse
    print("3. RWG RF Pulse:")
    waveforms = (StaticWaveform(sbg_id=0, freq=10.0, amp=0.5, phase=0.0),)
    start_state = RWGActive(carrier_freq=1000.0, rf_on=False, waveforms=waveforms)
    rf_pulse_morph = rwg.rf_pulse(40.0)(rwg_ch0, start_state)
    print(text_timeline(rf_pulse_morph, style='compact'))
    print()
    
    # Demo 4: Complex mixed operations
    print("4. Complex Mixed Operations:")
    mixed = parallel | rf_pulse_morph
    print(text_timeline(mixed, style='compact'))
    print()
    
    # Demo 5: Synchronization analysis
    print("5. Synchronization Analysis:")
    from catseq.visualization.timeline import _compute_physical_lanes
    physical_lanes = _compute_physical_lanes(mixed)
    sync_points = detect_sync_points(physical_lanes)
    
    print(f"Detected {len(sync_points)} synchronization points:")
    for i, sp in enumerate(sync_points):
        channels = [ch.global_id for ch in sp['channels']]
        print(f"  S{i+1}: t={sp['time_us']:.1f}μs - {', '.join(channels)}")
    print()
    
    # Demo 6: Timing analysis
    print("6. Timing Analysis:")
    timing_info = analyze_morphism_timing(mixed)
    print(f"Total duration: {timing_info['total_duration_us']:.1f}μs")
    print(f"Total channels: {timing_info['total_channels']}")
    print(f"Total boards: {timing_info['total_boards']}")
    print(f"Synchronization points: {timing_info['sync_points']}")
    print(f"Operation count: {timing_info['operation_count']}")
    print(f"Sync coverage: {timing_info['sync_coverage']:.1%}")
    print()
    
    # Demo 7: Pulse pattern detection
    print("7. Pulse Pattern Detection:")
    patterns = detect_pulse_patterns(mixed)
    print(f"Detected {len(patterns)} pulse patterns:")
    for pattern in patterns:
        ch = pattern['channel'].global_id
        print(f"  {pattern['type']}: {ch} - {pattern['duration']:.1f}μs at t={pattern['start_time']:.1f}μs")
    print()
    
    # Demo 8: Adaptive time scaling demonstration
    print("8. Adaptive Time Scaling:")
    
    # Create extreme time scale differences
    quick_start = ttl.pulse(ttl_ch0, 0.5)    # 0.5μs - very short
    long_gap = identity(200.0)               # 200μs - long wait  
    quick_end = ttl.pulse(ttl_ch1, 1.0)      # 1μs - short
    
    adaptive_demo = quick_start >> long_gap >> quick_end
    print("Sequence with extreme time differences:")
    print(text_timeline(adaptive_demo, style='compact'))
    print()
    
    # Demo 9: Universal interface
    print("9. Universal Interface Examples:")
    
    # Text mode
    text_result = visualize_morphism(simple_pulse, mode='text', style='compact')
    print("Text mode result:")
    print(text_result[:100] + "..." if len(text_result) > 100 else text_result)
    print()
    
    # Plot mode (creates matplotlib figure)
    fig, ax = visualize_morphism(simple_pulse, mode='plot', figsize=(8, 4))
    print(f"Plot mode result: Figure with {len(ax.patches)} patches and {len(ax.lines)} lines")
    
    # Save plot example (in examples directory)
    plot_timeline(mixed, filename='examples/demo_timeline.png', figsize=(12, 6))
    print("✅ Saved timeline plot to 'examples/demo_timeline.png'")
    print()
    
    print("=== Demo Complete ===")
    print("The new functional visualization interface provides:")
    print("✅ Pure functions - no morphism class modification needed")
    print("✅ Compiler integration - precise timing from PhysicalLane")
    print("✅ Pulse pattern recognition - intelligent operation grouping")
    print("✅ Sync detection - automatic synchronization analysis")
    print("✅ Multiple output formats - text and matplotlib plots")
    print("✅ Adaptive time scaling - ensures all operations are visible")
    print("✅ Scalable design - handles large time spans efficiently")


if __name__ == "__main__":
    demo_functional_visualization()