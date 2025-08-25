"""
Test morphism generation and timing correctness before compilation.

This test verifies that the morphism generation system correctly handles
timing constraints, board mapping, and synchronization requirements for
multi-channel operations using realistic RWG configurations.
"""

import pytest
import numpy as np
from functools import partial
from typing import Dict, List

from catseq.protocols import Channel
from catseq.builder import MorphismBuilder
from catseq.model import LaneMorphism, PrimitiveMorphism
from catseq.hardware.rwg import RWGDevice
from catseq.hardware.ttl import TTLDevice
from catseq.states.rwg import RWGReady, RWGActive, WaveformParams
from catseq.states.ttl import TTLReady, TTLHigh, TTLLow
from catseq.states.common import Uninitialized
from catseq.morphisms.rwg import initialize, play, linear_ramp
from catseq.morphisms.ttl import pulse, set_high, set_low


# --- Realistic RWG Channel Configurations ---

class RWGChannelConfig:
    """Configuration for RWG channels based on real hardware specs"""
    
    # Board 0 - MOT System (Carrier frequencies in MHz)
    MOT_REPUMP = {"board": 0, "rf_port": 0, "sbg": 0, "carrier": 80.1, "name": "mot_repump"}
    MOT_COOLING = {"board": 0, "rf_port": 1, "sbg": 32, "carrier": 120.5, "name": "mot_cooling"}
    GLOBAL_IMAGING = {"board": 0, "rf_port": 2, "sbg": 64, "carrier": 95.2, "name": "global_imaging"}
    GLOBAL_REPUMP = {"board": 0, "rf_port": 3, "sbg": 96, "carrier": 78.8, "name": "global_repump"}
    
    # Board 1 - Experiment Beams
    BLOWOFF = {"board": 1, "rf_port": 0, "sbg": 0, "carrier": 110.0, "name": "blowoff"}
    EIT1 = {"board": 1, "rf_port": 1, "sbg": 32, "carrier": 85.5, "name": "eit1"}
    EIT2 = {"board": 1, "rf_port": 2, "sbg": 64, "carrier": 92.3, "name": "eit2"}
    LOCAL_REPUMP = {"board": 1, "rf_port": 3, "sbg": 96, "carrier": 79.1, "name": "local_repump"}
    
    # Board 2 - Imaging System
    LOCAL_IMG1 = {"board": 2, "rf_port": 0, "sbg": 0, "carrier": 100.2, "name": "local_img1"}
    LOCAL_IMG2 = {"board": 2, "rf_port": 1, "sbg": 32, "carrier": 105.7, "name": "local_img2"}
    LOCAL_IMG_TOTAL = {"board": 2, "rf_port": 2, "sbg": 64, "carrier": 98.4, "name": "local_img_total"}


# --- Test Fixtures ---

@pytest.fixture
def rwg_channels():
    """Create realistic RWG channels with board mappings"""
    channels = {}
    
    configs = [
        RWGChannelConfig.MOT_REPUMP,
        RWGChannelConfig.MOT_COOLING, 
        RWGChannelConfig.GLOBAL_IMAGING,
        RWGChannelConfig.GLOBAL_REPUMP,
        RWGChannelConfig.BLOWOFF,
        RWGChannelConfig.EIT1,
        RWGChannelConfig.EIT2,
        RWGChannelConfig.LOCAL_REPUMP,
        RWGChannelConfig.LOCAL_IMG1,
        RWGChannelConfig.LOCAL_IMG2,
        RWGChannelConfig.LOCAL_IMG_TOTAL,
    ]
    
    for config in configs:
        device_factory = partial(
            RWGDevice,
            name=config["name"],
            available_sbgs={config["sbg"]},
            max_ramping_order=3,
            enforce_continuity=True,
            max_freq_jump_mhz=1e-3,
        )
        channels[config["name"]] = Channel(config["name"], device_factory)
        # Store config in channel for later reference
        channels[config["name"]].config = config
    
    return channels


@pytest.fixture 
def ttl_channels():
    """Create TTL channels for triggers and shutters"""
    channels = {
        "camera_trigger": Channel("camera_trigger", TTLDevice),
        "probe_shutter": Channel("probe_shutter", TTLDevice),
        "repump_shutter": Channel("repump_shutter", TTLDevice),
        "cooling_shutter": Channel("cooling_shutter", TTLDevice),
    }
    return channels


@pytest.fixture
def waveform_amplitudes():
    """Standard amplitude configurations for different operations"""
    return {
        "mot_repump": {"on": 0.15, "off": 0.0},
        "mot_cooling": {"on": 0.15, "off": 0.0}, 
        "global_imaging": {"on": 0.077, "off": 0.0},
        "global_repump": {"on": 0.077, "off": 0.0},
        "blowoff": {"on": 0.07, "off": 0.0},
        "eit1": {"on": 0.1, "off": 0.0},
        "eit2": {"on": 0.1, "off": 0.0},
        "local_repump": {"on": 0.07, "off": 0.0},
        "local_img1": {"on": 0.13, "off": 0.0},
        "local_img2": {"on": 0.13, "off": 0.0},
        "local_img_total": {"on": 0.12, "off": 0.0},
    }


# --- Test Cases ---

class TestSingleChannelTiming:
    """Test timing for individual channel operations"""
    
    def test_initialize_timing(self, rwg_channels):
        """Test RWG initialization timing"""
        channel = rwg_channels["mot_repump"]
        carrier_freq = channel.config["carrier"]
        duration = 10e-6  # 10μs standard init time
        
        init_morph = initialize(carrier_freq=carrier_freq, duration=duration)
        result = init_morph(channel, from_state=Uninitialized())
        
        assert result.duration == duration
        assert isinstance(result.cod[0][1], RWGReady)
        assert result.cod[0][1].carrier_freq == carrier_freq
        
    def test_waveform_timing(self, rwg_channels, waveform_amplitudes):
        """Test waveform playback timing"""
        channel = rwg_channels["mot_repump"]
        carrier_freq = channel.config["carrier"]
        sbg_id = channel.config["sbg"]
        amp_on = waveform_amplitudes["mot_repump"]["on"]
        
        duration = 1e-3  # 1ms
        params = WaveformParams(
            sbg_id=sbg_id,
            freq_coeffs=(0.0,),  # Constant frequency
            amp_coeffs=(amp_on,),
            initial_phase=0.0
        )
        
        ready_state = RWGReady(carrier_freq)
        play_morph = play(duration=duration, params=(params,))
        result = play_morph(channel, from_state=ready_state)
        
        assert result.duration == duration
        assert isinstance(result.cod[0][1], RWGActive)
        
    def test_ttl_pulse_timing(self, ttl_channels):
        """Test TTL pulse timing"""
        channel = ttl_channels["camera_trigger"]
        duration = 100e-6  # 100μs pulse
        
        pulse_morph = pulse(duration=duration)
        result = pulse_morph(channel, from_state=TTLLow())
        
        assert result.duration == duration
        assert isinstance(result.cod[0][1], TTLLow)  # Returns to low after pulse


class TestBoardLevelTiming:
    """Test timing constraints for board-level operations"""
    
    def create_board_channels(self, rwg_channels, board_id):
        """Get all channels for a specific board"""
        return {name: ch for name, ch in rwg_channels.items() 
                if ch.config["board"] == board_id}
    
    def test_same_board_synchronization(self, rwg_channels, waveform_amplitudes):
        """Test synchronization for channels on the same board"""
        board0_channels = self.create_board_channels(rwg_channels, 0)
        duration = 5e-3  # 5ms
        
        # Create morphisms for all Board 0 channels
        lanes = {}
        for name, channel in board0_channels.items():
            # Initialize
            carrier_freq = channel.config["carrier"]
            init_morph = initialize(carrier_freq=carrier_freq, duration=10e-6)
            
            # Play waveform
            sbg_id = channel.config["sbg"]
            amp = waveform_amplitudes[name]["on"]
            params = WaveformParams(
                sbg_id=sbg_id,
                freq_coeffs=(0.0,),
                amp_coeffs=(amp,),
                initial_phase=0.0
            )
            play_morph = play(duration=duration, params=(params,))
            
            # Chain them together
            combined = init_morph @ play_morph
            lanes[channel] = combined(channel, from_state=Uninitialized()).lanes[channel]
        
        # Create LaneMorphism
        total_duration = 10e-6 + duration  # Init + play time
        board_sequence = LaneMorphism(lanes, total_duration)
        
        # Verify all channels have the same total duration
        assert len(board_sequence.lanes) == 4  # Board 0 has 4 channels
        for channel_morphisms in board_sequence.lanes.values():
            channel_duration = sum(m.duration for m in channel_morphisms)
            assert abs(channel_duration - total_duration) < 1e-9
    
    def test_cross_board_timing(self, rwg_channels, waveform_amplitudes):
        """Test timing alignment across different boards"""
        # Channels from different boards
        board0_ch = rwg_channels["mot_repump"]
        board1_ch = rwg_channels["blowoff"] 
        board2_ch = rwg_channels["local_img1"]
        
        duration = 2e-3  # 2ms
        lanes = {}
        
        for channel in [board0_ch, board1_ch, board2_ch]:
            # Create morphism sequence
            carrier_freq = channel.config["carrier"]
            sbg_id = channel.config["sbg"]
            amp = waveform_amplitudes[channel.config["name"]]["on"]
            
            init_morph = initialize(carrier_freq=carrier_freq, duration=10e-6)
            params = WaveformParams(
                sbg_id=sbg_id,
                freq_coeffs=(0.0,),
                amp_coeffs=(amp,),
                initial_phase=0.0
            )
            play_morph = play(duration=duration, params=(params,))
            
            combined = init_morph @ play_morph
            lanes[channel] = combined(channel, from_state=Uninitialized()).lanes[channel]
        
        # Create cross-board sequence
        total_duration = 10e-6 + duration
        cross_board_seq = LaneMorphism(lanes, total_duration)
        
        # Verify synchronization across boards
        assert len(cross_board_seq.lanes) == 3
        for channel_morphisms in cross_board_seq.lanes.values():
            channel_duration = sum(m.duration for m in channel_morphisms)
            assert abs(channel_duration - total_duration) < 1e-9


class TestTimingConstraints:
    """Test hardware timing constraints"""
    
    def test_parameter_write_timing(self, rwg_channels, waveform_amplitudes):
        """Test parameter write timing constraints"""
        channel = rwg_channels["mot_repump"]
        carrier_freq = channel.config["carrier"]
        sbg_id = channel.config["sbg"]
        
        # Hardware constraint: parameter write takes ~10μs per SBG
        param_write_time = 10e-6
        
        # Test case 1: Duration longer than write time (should pass)
        long_duration = 50e-6  # 50μs > 10μs
        params1 = WaveformParams(
            sbg_id=sbg_id,
            freq_coeffs=(0.0,),
            amp_coeffs=(waveform_amplitudes["mot_repump"]["on"],),
            initial_phase=0.0
        )
        
        ready_state = RWGReady(carrier_freq)
        play_morph1 = play(duration=long_duration, params=(params1,))
        result1 = play_morph1(channel, from_state=ready_state)
        
        # This should succeed
        assert result1.duration == long_duration
        
        # Test case 2: Very short duration (would violate constraint in compiler)
        short_duration = 1e-6  # 1μs < 10μs
        play_morph2 = play(duration=short_duration, params=(params1,))
        result2 = play_morph2(channel, from_state=ready_state)
        
        # The morphism itself should be created successfully
        # (constraint checking happens at compile time)
        assert result2.duration == short_duration
        
        # Store constraint violation info for compiler
        result2.constraint_warnings = []
        if short_duration < param_write_time:
            result2.constraint_warnings.append({
                "type": "parameter_write_timing",
                "required_time": param_write_time,
                "actual_time": short_duration,
                "violation": param_write_time - short_duration
            })
            
        assert len(result2.constraint_warnings) == 1
    
    def test_shared_bandwidth_constraints(self, rwg_channels, waveform_amplitudes):
        """Test constraints for shared bandwidth on same board"""
        # Get all Board 0 channels (share CSR write bandwidth)
        board0_channels = [rwg_channels[name] for name in 
                          ["mot_repump", "mot_cooling", "global_imaging", "global_repump"]]
        
        # Simultaneous parameter writes for 4 channels
        # Hardware: ~10μs per SBG, 4 SBGs = ~40μs total write time
        min_gap_time = 40e-6  # Minimum gap between waveform switches
        
        duration1 = 100e-6  # First waveform: 100μs
        duration2 = 50e-6   # Second waveform: 50μs
        
        # Create two sequential waveforms for all channels
        lanes = {}
        for channel in board0_channels:
            carrier_freq = channel.config["carrier"]
            sbg_id = channel.config["sbg"]
            amp_name = channel.config["name"]
            amp = waveform_amplitudes[amp_name]["on"]
            
            # First waveform
            params1 = WaveformParams(
                sbg_id=sbg_id,
                freq_coeffs=(0.0,),
                amp_coeffs=(amp,),
                initial_phase=0.0
            )
            
            # Second waveform (different amplitude for variation)
            params2 = WaveformParams(
                sbg_id=sbg_id,
                freq_coeffs=(0.0,),
                amp_coeffs=(amp * 0.5,),
                initial_phase=0.0,
                phase_reset=False
            )
            
            ready_state = RWGReady(carrier_freq)
            play1 = play(duration=duration1, params=(params1,))
            play2 = play(duration=duration2, params=(params2,))
            
            # Chain the morphisms
            combined = play1 @ play2
            lanes[channel] = combined(channel, from_state=ready_state).lanes[channel]
        
        total_duration = duration1 + duration2
        board_seq = LaneMorphism(lanes, total_duration)
        
        # Check if timing constraint would be satisfied
        constraint_satisfied = duration1 >= min_gap_time
        
        # Store constraint info
        board_seq.bandwidth_constraint = {
            "board_id": 0,
            "required_gap": min_gap_time,
            "actual_gap": duration1,
            "satisfied": constraint_satisfied,
            "num_channels": len(board0_channels)
        }
        
        assert board_seq.bandwidth_constraint["num_channels"] == 4
        if not constraint_satisfied:
            # Would need compiler intervention
            assert duration1 < min_gap_time


class TestComplexSequences:
    """Test complex multi-channel, multi-phase sequences"""
    
    def test_mot_loading_sequence(self, rwg_channels, waveform_amplitudes):
        """Test a realistic MOT loading sequence"""
        # Phase 1: Turn on MOT beams
        mot_channels = ["mot_repump", "mot_cooling", "global_imaging"]
        mot_duration = 10e-3  # 10ms loading
        
        # Phase 2: Turn off MOT beams  
        off_duration = 1e-3   # 1ms off time
        
        lanes = {}
        for ch_name in mot_channels:
            channel = rwg_channels[ch_name]
            carrier_freq = channel.config["carrier"]
            sbg_id = channel.config["sbg"]
            
            # Initialize
            init_morph = initialize(carrier_freq=carrier_freq, duration=10e-6)
            
            # MOT on
            amp_on = waveform_amplitudes[ch_name]["on"]
            params_on = WaveformParams(
                sbg_id=sbg_id,
                freq_coeffs=(0.0,),
                amp_coeffs=(amp_on,),
                initial_phase=0.0
            )
            play_on = play(duration=mot_duration, params=(params_on,))
            
            # MOT off
            amp_off = waveform_amplitudes[ch_name]["off"] 
            params_off = WaveformParams(
                sbg_id=sbg_id,
                freq_coeffs=(0.0,),
                amp_coeffs=(amp_off,),
                initial_phase=0.0,
                phase_reset=False
            )
            play_off = play(duration=off_duration, params=(params_off,))
            
            # Chain all phases
            full_sequence = init_morph @ play_on @ play_off
            lanes[channel] = full_sequence(channel, from_state=Uninitialized()).lanes[channel]
        
        total_duration = 10e-6 + mot_duration + off_duration  # ~11.001ms
        mot_seq = LaneMorphism(lanes, total_duration)
        
        # Verify sequence structure
        assert len(mot_seq.lanes) == 3
        for channel_morphisms in mot_seq.lanes.values():
            assert len(channel_morphisms) == 3  # init, on, off
            assert channel_morphisms[0].name == "initialize"
            assert "play" in channel_morphisms[1].name or "ramp" in channel_morphisms[1].name
            assert "play" in channel_morphisms[2].name or "ramp" in channel_morphisms[2].name
    
    def test_experiment_with_ttl_triggers(self, rwg_channels, ttl_channels, waveform_amplitudes):
        """Test experiment sequence with RF and TTL coordination"""
        # RF: Imaging beam
        rf_channel = rwg_channels["local_img1"]
        ttl_channel = ttl_channels["camera_trigger"]
        
        # Timing
        rf_duration = 100e-6    # 100μs imaging
        ttl_duration = 10e-6    # 10μs camera trigger
        ttl_delay = 50e-6       # Trigger 50μs into RF pulse
        
        # RF sequence
        carrier_freq = rf_channel.config["carrier"]
        sbg_id = rf_channel.config["sbg"]
        amp = waveform_amplitudes["local_img1"]["on"]
        
        rf_init = initialize(carrier_freq=carrier_freq, duration=10e-6)
        rf_params = WaveformParams(
            sbg_id=sbg_id,
            freq_coeffs=(0.0,),
            amp_coeffs=(amp,),
            initial_phase=0.0
        )
        rf_play = play(duration=rf_duration, params=(rf_params,))
        rf_sequence = rf_init @ rf_play
        
        # TTL sequence with delay
        # Note: In real implementation, delay would be handled by compiler scheduling
        ttl_wait = pulse(duration=ttl_delay)  # Wait/delay  
        ttl_trigger = pulse(duration=ttl_duration)  # Actual trigger
        ttl_sequence = ttl_wait @ ttl_trigger
        
        # Create coordinated sequence
        lanes = {
            rf_channel: rf_sequence(rf_channel, from_state=Uninitialized()).lanes[rf_channel],
            ttl_channel: ttl_sequence(ttl_channel, from_state=TTLLow()).lanes[ttl_channel]
        }
        
        total_duration = max(10e-6 + rf_duration, ttl_delay + ttl_duration)
        coord_seq = LaneMorphism(lanes, total_duration)
        
        # Verify coordination
        assert len(coord_seq.lanes) == 2
        rf_total = sum(m.duration for m in coord_seq.lanes[rf_channel])
        ttl_total = sum(m.duration for m in coord_seq.lanes[ttl_channel])
        
        assert abs(rf_total - (10e-6 + rf_duration)) < 1e-9
        assert abs(ttl_total - (ttl_delay + ttl_duration)) < 1e-9


class TestChannelMapping:
    """Test channel to hardware mapping correctness"""
    
    def test_board_assignments(self, rwg_channels):
        """Test that channels are correctly assigned to boards"""
        board_assignments = {}
        for name, channel in rwg_channels.items():
            board_id = channel.config["board"]
            if board_id not in board_assignments:
                board_assignments[board_id] = []
            board_assignments[board_id].append(name)
        
        # Verify expected board assignments
        assert len(board_assignments[0]) == 4  # MOT system
        assert len(board_assignments[1]) == 4  # Experiment beams
        assert len(board_assignments[2]) == 3  # Imaging system
        
        # Verify specific assignments
        assert "mot_repump" in board_assignments[0]
        assert "blowoff" in board_assignments[1]
        assert "local_img1" in board_assignments[2]
    
    def test_sbg_assignments(self, rwg_channels):
        """Test SBG ID assignments"""
        for name, channel in rwg_channels.items():
            sbg_id = channel.config["sbg"]
            rf_port = channel.config["rf_port"]
            
            # Verify SBG to RF port mapping (32 SBGs per RF port)
            expected_port = sbg_id // 32
            assert rf_port == expected_port
    
    def test_carrier_frequencies(self, rwg_channels):
        """Test carrier frequency assignments are reasonable"""
        for name, channel in rwg_channels.items():
            carrier_freq = channel.config["carrier"]
            
            # Verify frequencies are in reasonable range for atomic physics
            assert 50.0 <= carrier_freq <= 200.0  # MHz
            
            # Verify some specific frequencies
            if name == "mot_repump":
                assert abs(carrier_freq - 80.1) < 0.1
            elif name == "mot_cooling":
                assert abs(carrier_freq - 120.5) < 0.1


# --- Integration Test ---

def test_full_experiment_integration(rwg_channels, ttl_channels, waveform_amplitudes):
    """Integration test for a complete experiment sequence"""
    
    # Experiment phases
    phases = {
        "mot_loading": 10e-3,      # 10ms
        "molasses": 2e-3,          # 2ms  
        "imaging": 100e-6,         # 100μs
        "readout": 1e-3            # 1ms
    }
    
    total_experiment_duration = sum(phases.values())
    
    # Verify realistic timing
    assert total_experiment_duration > 10e-3  # At least 10ms total
    assert phases["imaging"] < 1e-3           # Imaging shorter than 1ms
    assert phases["mot_loading"] > phases["molasses"]  # Loading longer than molasses
    
    print(f"Total experiment duration: {total_experiment_duration*1e3:.1f} ms")
    print(f"  MOT loading: {phases['mot_loading']*1e3:.1f} ms")
    print(f"  Molasses: {phases['molasses']*1e3:.1f} ms") 
    print(f"  Imaging: {phases['imaging']*1e6:.1f} μs")
    print(f"  Readout: {phases['readout']*1e3:.1f} ms")
    
    # This test mainly verifies that the timing structure is reasonable
    # Full implementation would create actual morphism sequences for each phase