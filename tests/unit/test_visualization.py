#!/usr/bin/env python3
"""
Test morphism visualization capabilities using functional interface
"""

import pytest
from catseq.types import Board, Channel, ChannelType
from catseq.types.ttl import TTLState
from catseq.types.rwg import RWGActive, StaticWaveform
from catseq.hardware import ttl, rwg
from catseq.atomic import ttl_on, ttl_off
from catseq.morphism import identity
from catseq.visualization import (
    visualize_morphism,
    plot_timeline,
    text_timeline,
    analyze_morphism_timing,
    detect_sync_points,
    detect_pulse_patterns,
)

def test_functional_visualization_interface():
    """Test functional visualization interface works correctly"""
    
    # Create test channels
    board = Board("RWG_0")
    ttl_ch0 = Channel(board=board, channel_type=ChannelType.TTL, local_id=0)
    ttl_ch1 = Channel(board=board, channel_type=ChannelType.TTL, local_id=1)
    rwg_ch0 = Channel(board=board, channel_type=ChannelType.RWG, local_id=0)
    
    # Test 1: Text visualization
    pulse = ttl.pulse(ttl_ch0, 50.0)
    text_output = text_timeline(pulse, style='compact')
    assert "Timeline View" in text_output
    assert "TTL" in text_output
    
    # Test 2: Plot visualization (returns matplotlib objects)
    fig, ax = plot_timeline(pulse, figsize=(8, 4))
    assert fig is not None
    assert ax is not None
    
    # Test 3: Universal interface
    text_result = visualize_morphism(pulse, mode='text', style='compact')
    plot_result = visualize_morphism(pulse, mode='plot', figsize=(6, 3))
    assert isinstance(text_result, str)
    assert len(plot_result) == 2  # (fig, ax) tuple
    
    # Test 4: Analysis functions
    timing_info = analyze_morphism_timing(pulse)
    assert 'total_duration_us' in timing_info
    assert timing_info['total_channels'] > 0


def test_pulse_pattern_detection():
    """Test functional pulse pattern detection"""
    board = Board("TEST")
    ttl_ch = Channel(board=board, channel_type=ChannelType.TTL, local_id=0)
    
    # Test TTL pulse detection
    pulse = ttl.pulse(ttl_ch, 25.0)
    patterns = detect_pulse_patterns(pulse)
    
    # Should detect TTL pulse
    ttl_patterns = [p for p in patterns if p['type'] == 'TTL_PULSE']
    assert len(ttl_patterns) >= 1
    assert ttl_patterns[0]['duration'] == 25.0


def test_sync_detection():
    """Test synchronization point detection"""
    board = Board("TEST")
    ttl_ch0 = Channel(board=board, channel_type=ChannelType.TTL, local_id=0)
    ttl_ch1 = Channel(board=board, channel_type=ChannelType.TTL, local_id=1)
    
    # Create parallel pulses (should have sync points)
    pulse1 = ttl.pulse(ttl_ch0, 30.0)
    pulse2 = ttl.pulse(ttl_ch1, 20.0)
    parallel = pulse1 | pulse2
    
    # Use compiler components to detect sync
    from catseq.visualization.timeline import _compute_physical_lanes
    physical_lanes = _compute_physical_lanes(parallel)
    sync_points = detect_sync_points(physical_lanes)
    
    # Should detect sync points at start
    assert len(sync_points) > 0
    # First sync point should be at t=0 (both pulses start together)
    assert sync_points[0]['time_us'] == 0.0


def test_large_timespan_handling():
    """Test handling of large time spans with functional interface"""
    board = Board("TEST")
    ttl_ch = Channel(board=board, channel_type=ChannelType.TTL, local_id=0)
    
    # Test with very large time span
    large_pulse = ttl.pulse(ttl_ch, 1000000.0)  # 1 second
    
    # Should handle gracefully without excessive memory usage
    text_result = text_timeline(large_pulse, style='compact', max_width=100)
    assert "Timeline View" in text_result
    assert len(text_result) < 10000  # Should be reasonably sized
    
    # Analysis should work
    timing_info = analyze_morphism_timing(large_pulse)
    assert abs(timing_info['total_duration_us'] - 1000000.0) < 0.01  # Allow small floating point error


if __name__ == "__main__":
    # For manual testing/debugging
    test_functional_visualization_interface()
    test_pulse_pattern_detection()
    test_sync_detection()
    test_large_timespan_handling()
    print("All functional visualization tests passed!")