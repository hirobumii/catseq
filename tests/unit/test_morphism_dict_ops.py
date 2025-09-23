#!/usr/bin/env python3
"""
Unit tests for Morphism dictionary operations (>> {}).

Tests the new dictionary syntax for multi-channel operations with automatic
state propagation and time alignment.
"""

import pytest
from catseq.types import Board, Channel, ChannelType
from catseq.types.rwg import RWGUninitialized, RWGReady, RWGActive, StaticWaveform
from catseq.types.ttl import TTLState
from catseq.hardware import rwg, ttl
from catseq.hardware.rwg import RWGTarget
from catseq.morphism import Morphism, identity
from catseq.time_utils import us_to_cycles
from catseq import us  # Import microsecond unit


class TestMorphismDictOperations:
    """Test the >> {} dictionary operation syntax."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.board = Board("test_board")
        self.ch1 = Channel(self.board, 0, ChannelType.RWG)
        self.ch2 = Channel(self.board, 1, ChannelType.RWG) 
        self.ch3 = Channel(self.board, 2, ChannelType.RWG)
        self.ttl_ch = Channel(self.board, 0, ChannelType.TTL)

    def test_basic_dict_operation(self):
        """Test basic dictionary operation with two channels."""
        # Create initial morphism with two channels
        init_morphism = rwg.initialize(100.0)(self.ch1) | rwg.initialize(200.0)(self.ch2)
        
        # Apply different operations to each channel
        target1 = RWGTarget(freq=10.0, amp=0.5, sbg_id=0)
        target2 = RWGTarget(freq=20.0, amp=0.8, sbg_id=0)
        
        result = init_morphism >> {
            self.ch1: rwg.set_state([target1]),
            self.ch2: rwg.set_state([target2])
        }
        
        # Verify result has both channels
        assert self.ch1 in result.lanes
        assert self.ch2 in result.lanes
        
        # Verify both channels have the same total duration
        ch1_duration = result.lanes[self.ch1].total_duration_cycles
        ch2_duration = result.lanes[self.ch2].total_duration_cycles
        assert ch1_duration == ch2_duration

    def test_empty_dict_returns_original(self):
        """Test that empty dictionary returns the original morphism."""
        init_morphism = rwg.initialize(100.0)(self.ch1)
        result = init_morphism >> {}
        
        assert result is init_morphism

    def test_time_alignment_with_different_durations(self):
        """Test automatic time alignment when operations have different durations."""
        # Create initial morphism
        init_morphism = (rwg.initialize(100.0)(self.ch1) | 
                        rwg.initialize(200.0)(self.ch2) |
                        rwg.initialize(300.0)(self.ch3))
        
        # Operations with different durations
        target = RWGTarget(freq=10.0, amp=0.5, sbg_id=0)
        
        result = init_morphism >> {
            self.ch1: rwg.set_state([target]),           # ~instant
            self.ch2: rwg.hold(5.0 * us),                # 5μs  
            # ch3 not specified - should get auto wait
        }
        
        # All channels should have the same duration (1μs init + 5μs from longest operation = 6μs)
        expected_duration = us_to_cycles(6.0)
        for channel in [self.ch1, self.ch2, self.ch3]:
            lane_duration = result.lanes[channel].total_duration_cycles
            # Allow small tolerance for calculation differences
            assert abs(lane_duration - expected_duration) <= 1

    def test_unspecified_channels_get_identity(self):
        """Test that unspecified channels get identity operations."""
        init_morphism = rwg.initialize(100.0)(self.ch1) | rwg.initialize(200.0)(self.ch2)
        
        # Only operate on ch1, ch2 should get identity
        result = init_morphism >> {
            self.ch1: rwg.hold(10.0)  # 10μs operation
        }
        
        # Both channels should have same duration
        ch1_duration = result.lanes[self.ch1].total_duration_cycles
        ch2_duration = result.lanes[self.ch2].total_duration_cycles
        assert ch1_duration == ch2_duration
        
        # ch2 should have an additional identity operation
        ch2_ops = result.lanes[self.ch2].operations
        # Should have: initialize + identity (for wait)
        assert len(ch2_ops) >= 2

    def test_chain_multiple_dict_operations(self):
        """Test chaining multiple dictionary operations."""
        init_morphism = rwg.initialize(100.0)(self.ch1) | rwg.initialize(200.0)(self.ch2)
        
        target1 = RWGTarget(freq=10.0, amp=0.5, sbg_id=0)
        target2 = RWGTarget(freq=20.0, amp=0.8, sbg_id=0)
        target3 = RWGTarget(freq=30.0, amp=0.3, sbg_id=0)
        
        result = (init_morphism 
                 >> {self.ch1: rwg.set_state([target1]), self.ch2: rwg.hold(2.0)}
                 >> {self.ch1: rwg.hold(1.0), self.ch2: rwg.set_state([target2])} 
                 >> {self.ch1: rwg.set_state([target3])})
        
        # Should have both channels with equal durations
        assert self.ch1 in result.lanes
        assert self.ch2 in result.lanes
        
        ch1_duration = result.lanes[self.ch1].total_duration_cycles
        ch2_duration = result.lanes[self.ch2].total_duration_cycles
        assert ch1_duration == ch2_duration

    def test_error_on_nonexistent_channel(self):
        """Test error when dictionary contains a channel not in the morphism."""
        init_morphism = rwg.initialize(100.0)(self.ch1)
        
        # ch2 is not in init_morphism
        with pytest.raises(ValueError, match="Channel.*not found in morphism"):
            init_morphism >> {
                self.ch1: rwg.hold(1.0),
                self.ch2: rwg.hold(1.0)  # This should cause error
            }

    def test_type_checking_rejects_invalid_dict(self):
        """Test that invalid dictionary types are rejected."""
        init_morphism = rwg.initialize(100.0)(self.ch1)
        
        # Invalid key type should raise TypeError
        with pytest.raises(TypeError, match="unsupported operand type"):
            init_morphism >> {"not_a_channel": rwg.hold(1.0)}
        
        # Invalid value type should raise TypeError  
        with pytest.raises(TypeError, match="unsupported operand type"):
            init_morphism >> {self.ch1: "not_a_morphism_def"}

    def test_mixed_channel_types(self):
        """Test dictionary operations with different channel types."""
        # Create morphism with both RWG and TTL channels  
        init_morphism = rwg.initialize(100.0)(self.ch1) | ttl.off()(self.ttl_ch)
        
        target = RWGTarget(freq=10.0, amp=0.5, sbg_id=0)
        
        result = init_morphism >> {
            self.ch1: rwg.set_state([target]),
            self.ttl_ch: ttl.hold(3.0)
        }
        
        # Should work with mixed channel types
        assert self.ch1 in result.lanes
        assert self.ttl_ch in result.lanes

    def test_zero_duration_operations(self):
        """Test handling of zero-duration operations."""
        init_morphism = rwg.initialize(100.0)(self.ch1) | rwg.initialize(200.0)(self.ch2)
        
        target = RWGTarget(freq=10.0, amp=0.5, sbg_id=0)
        
        # One instant operation, one with duration
        result = init_morphism >> {
            self.ch1: rwg.set_state([target]),  # Instant
            self.ch2: rwg.hold(0.0)            # Also instant
        }
        
        # Both should end up with same (zero or minimal) additional duration
        ch1_duration = result.lanes[self.ch1].total_duration_cycles  
        ch2_duration = result.lanes[self.ch2].total_duration_cycles
        assert ch1_duration == ch2_duration

    def test_equivalence_with_manual_parallel_composition(self):
        """Test that dictionary operations are equivalent to manual | composition."""
        init_morphism = rwg.initialize(100.0)(self.ch1) | rwg.initialize(200.0)(self.ch2)
        
        target1 = RWGTarget(freq=10.0, amp=0.5, sbg_id=0)
        target2 = RWGTarget(freq=20.0, amp=0.8, sbg_id=0)
        
        # Dictionary approach
        dict_result = init_morphism >> {
            self.ch1: rwg.set_state([target1]),
            self.ch2: rwg.set_state([target2])
        }
        
        # Manual approach (what we want to replace)
        ch1_end_state = init_morphism.lanes[self.ch1].operations[-1].end_state
        ch2_end_state = init_morphism.lanes[self.ch2].operations[-1].end_state
        
        manual_result = (init_morphism >> 
                        (rwg.set_state([target1])(self.ch1, ch1_end_state) |
                         rwg.set_state([target2])(self.ch2, ch2_end_state)))
        
        # Results should be equivalent
        assert dict_result.total_duration_cycles == manual_result.total_duration_cycles
        assert len(dict_result.lanes) == len(manual_result.lanes)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])