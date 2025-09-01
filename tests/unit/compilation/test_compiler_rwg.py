"""
Tests for the RWG-specific logic in the compiler.
"""

import pytest

from catseq.types.common import Board, Channel, ChannelType, OperationType
from catseq.compilation.types import OASMAddress, OASMFunction
from catseq.types.rwg import WaveformParams
from catseq.hardware import rwg
from catseq.compilation.compiler import compile_to_oasm_calls

def test_pass1_cost_analysis(capsys):
    """
    Tests that Pass 1 correctly identifies RWG_LOAD_COEFFS operations
    and annotates them with a calculated cost.
    """
    # 1. Arrange
    board = Board("RWG0")
    rwg_ch = Channel(board, 0, ChannelType.RWG)

    # This sequence has two RWG_LOAD_COEFFS operations.
    # The first (from set_state) has 1 param.
    # The second (from linear_ramp) has 1 param.
    sequence_def = (
        rwg.initialize(carrier_freq=100.0) >>
        rwg.set_state([rwg.InitialTarget(sbg_id=0, freq=10, amp=0.5)]) >>
        rwg.linear_ramp([rwg.RampTarget(target_freq=20, target_amp=0.8)], duration_us=10)
    )
    morphism = sequence_def(rwg_ch)

    # 2. Act: Run the compiler and get the internal events for inspection.
    events_by_board = compile_to_oasm_calls(morphism, _return_internal_events=True)

    # 3. Assert
    assert OASMAddress.RWG0 in events_by_board
    events = events_by_board[OASMAddress.RWG0]
    
    # Find the RWG_LOAD_COEFFS events
    load_events = [e for e in events if e.operation.operation_type == OperationType.RWG_LOAD_COEFFS]
    assert len(load_events) == 2

    # Check the cost of the first load event (from set_state)
    # It has 1 parameter, so cost should be 1 * 20 = 20
    assert load_events[0].cost_cycles == 20

    # Check the cost of the second load event (from linear_ramp)
    # It also has 1 parameter
    assert load_events[1].cost_cycles == 20

def test_pass3_generates_correct_rwg_calls():
    """
    Tests that Pass 3 generates the correct, non-pipelined OASM calls for a simple RWG sequence.
    """
    # 1. Arrange
    board = Board("RWG0")
    rwg_ch = Channel(board, 0, ChannelType.RWG)
    sequence_def = (
        rwg.initialize(carrier_freq=120.0) >>
        rwg.set_state([rwg.InitialTarget(sbg_id=0, freq=15, amp=0.6)])
    )
    morphism = sequence_def(rwg_ch)

    # 2. Act
    oasm_calls = compile_to_oasm_calls(morphism)

    # 3. Assert
    # We expect 4 calls: INIT, WAIT, LOAD, PLAY
    assert len(oasm_calls) == 4

    # Call 1: Initialize Port
    call1 = oasm_calls[0]
    assert call1.dsl_func == OASMFunction.RWG_INITIALIZE_PORT
    assert call1.args == (0, 120.0) # channel_id, carrier_freq

    # Call 2: Wait for init to complete
    call2 = oasm_calls[1]
    assert call2.dsl_func == OASMFunction.WAIT_US

    # Call 3: Load Waveform
    call3 = oasm_calls[2]
    assert call3.dsl_func == OASMFunction.RWG_LOAD_WAVEFORM
    expected_params = WaveformParams(
        sbg_id=0, freq_coeffs=(15, None, None, None), amp_coeffs=(0.6, None, None, None), initial_phase=0.0, phase_reset=True
    )
    assert call3.args[0] == expected_params

    # Call 4: Play (zero-duration for set_state)
    call4 = oasm_calls[3]
    assert call4.dsl_func == OASMFunction.RWG_PLAY
    assert call4.args[0] == 0.0 # duration_us
    assert call4.args[1] == 1   # pud_mask for ch0
    assert call4.args[2] == 1   # iou_mask for ch0

def test_pass3_pipelined_scheduling():
    """
    Tests that Pass 3 correctly schedules a pipelined LOAD operation.
    """
    # 1. Arrange
    board = Board("RWG0")
    rwg_ch = Channel(board, 0, ChannelType.RWG)
    # The first ramp (10us) is long enough to load the params for the second ramp.
    # 10us = 2500 cycles. Load cost is 1*20=20 cycles.
    sequence_def = (
        rwg.initialize(carrier_freq=100.0) >>
        rwg.set_state([rwg.InitialTarget(sbg_id=0, freq=10, amp=0.5)]) >>
        rwg.linear_ramp([rwg.RampTarget(target_freq=20, target_amp=0.8)], duration_us=10) >>
        rwg.linear_ramp([rwg.RampTarget(target_freq=15, target_amp=0.7)], duration_us=5)
    )
    morphism = sequence_def(rwg_ch)

    # 2. Act
    oasm_calls = compile_to_oasm_calls(morphism)

    # 3. Assert
    # Expected sequence of key operations:
    # ...
    # WAIT (up to start of first ramp)
    # RWG_PLAY (triggers first ramp)
    # RWG_LOAD_WAVEFORM (for the second ramp, pipelined)
    # WAIT (remainder of first ramp's duration)
    # RWG_PLAY (triggers second ramp)
    # ...
    func_sequence = [call.dsl_func for call in oasm_calls]

    # Find the first RWG_PLAY call
    first_play_index = func_sequence.index(OASMFunction.RWG_PLAY)
    
    # The very next call should be the pipelined LOAD
    pipelined_load_index = first_play_index + 1
    assert func_sequence[pipelined_load_index] == OASMFunction.RWG_LOAD_WAVEFORM

    # The next call should be a WAIT
    wait_index = pipelined_load_index + 1
    assert func_sequence[wait_index] == OASMFunction.WAIT_US

    # The next call should be the second PLAY
    second_play_index = wait_index + 1
    assert func_sequence[second_play_index] == OASMFunction.RWG_PLAY

def test_pass2_pipelining_constraint():
    """
    Tests the Pass 2 pipelining constraint check.
    """
    board = Board("RWG0")
    rwg_ch = Channel(board, 0, ChannelType.RWG)

    # --- Success Case --- 
    # Ramp duration (10us) is long enough for the next load (cost=20*1=20 cycles).
    # 10us = 2500 cycles at 250MHz. 2500 > 20.
    success_def = (
        rwg.initialize(carrier_freq=100.0) >>
        rwg.set_state([rwg.InitialTarget(sbg_id=0, freq=10, amp=0.5)]) >>
        rwg.linear_ramp([rwg.RampTarget(target_freq=20, target_amp=0.8)], duration_us=10) >>
        rwg.linear_ramp([rwg.RampTarget(target_freq=15, target_amp=0.7)], duration_us=5) 
    )
    morphism = success_def(rwg_ch)
    # This should compile without error
    compile_to_oasm_calls(morphism)

    # --- Failure Case ---
    # Ramp duration (0.05us) is too short. 0.05us = 12.5 cycles, which is < 20.
    fail_def = (
        rwg.initialize(carrier_freq=100.0) >>
        rwg.set_state([rwg.InitialTarget(sbg_id=0, freq=10, amp=0.5)]) >>
        rwg.linear_ramp([rwg.RampTarget(target_freq=20, target_amp=0.8)], duration_us=0.05) >>
        rwg.linear_ramp([rwg.RampTarget(target_freq=15, target_amp=0.7)], duration_us=5) 
    )
    morphism_fail = fail_def(rwg_ch)
    with pytest.raises(ValueError, match="Timing violation"):
        compile_to_oasm_calls(morphism_fail)
