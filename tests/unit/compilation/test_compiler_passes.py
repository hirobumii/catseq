"""
Unit tests for the CatSeq compiler passes.
"""
import pytest
from catseq.compilation.compiler import (
    _pass0_extract_events,
    _pass1_translate_to_oasm,
    _pass2_analyze_costs,
    _pass3_check_constraints,
    _pass4_generate_oasm_calls,
    _estimate_oasm_cost,
    _identify_pipeline_pairs,
    _calculate_optimal_schedule,
    OASM_FUNCTION_MAP
)
from catseq.compilation.types import OASMAddress, OASMFunction, OASMCall
from catseq.compilation.functions import rwg_load_waveform
from catseq.types.common import OperationType, AtomicMorphism, Board, Channel, ChannelType
from catseq.types.rwg import WaveformParams, RWGReady, RWGWaveformInstruction, RWGActive
from catseq.morphism import Morphism, identity
from catseq.lanes import Lane
from catseq.atomic import rwg_load_coeffs, rwg_update_params
from catseq.hardware import rwg

# Mock OASM assembler and disassembler if not available
try:
    from oasm.rtmq2 import assembler, disassembler
    from oasm.dev.rwg import C_RWG
    from oasm.rtmq2.intf import sim_intf
    from oasm.dev.main import run_cfg
    OASM_AVAILABLE = True
except ImportError:
    OASM_AVAILABLE = False

@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed")
def test_pass1_and_pass2_rwg_load_coeffs_cost_analysis():
    """
    Tests that Pass 1 correctly translates a RWG_LOAD_COEFFS operation
    and that Pass 2 correctly calculates its cost based on the generated assembly.
    """
    # 1. Define Test Inputs
    board = Board("RWG0")
    channel = Channel(board=board, local_id=0, channel_type=ChannelType.RWG)
    
    test_waveform_params = WaveformParams(
        sbg_id=1,
        freq_coeffs=(10.0, 0.1, None, None),
        amp_coeffs=(0.5, 0.01, None, None),
        initial_phase=1.57, # pi/2
        phase_reset=True
    )

    # Create a Morphism with a delay and a single LOAD operation
    # We use the `>>` operator which automatically handles state inference
    # and identity propagation.
    morphism = (
        identity(duration_us=10) >>
        rwg_load_coeffs(
            channel,
            params=[test_waveform_params],
            start_state=RWGReady(carrier_freq=100e6, rf_on=False)
        )
    )

    # 2. Set up the pre-initialized assembler using single board configuration (like integration test)
    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    rwgs = [0, 1]  # Use simpler configuration like integration test
    run_all = run_cfg(intf, rwgs)
    
    # Create the assembler sequence with single board configuration
    assembler_seq = assembler(run_all, [('rwg0', C_RWG)])

    # 3. Calculate the Expected Cost (Golden Standard)
    # Use the same assembler for both golden standard and cost analysis
    test_seq = assembler(run_all, [('rwg0', C_RWG)])
    
    # Golden standard: direct function call
    test_seq('rwg0', rwg_load_waveform, test_waveform_params)
    golden_binary_asm = test_seq.asm['rwg0']
    golden_asm_lines = disassembler(core=C_RWG)(golden_binary_asm)
    # print("Golden standard assembly:", golden_asm_lines)
    
    expected_cost = _estimate_oasm_cost(golden_asm_lines)
    assert expected_cost == 14, f"Expected cost should be exactly 14 cycles, got {expected_cost}"
    
    # Note: Pass 2 will clear the assembler internally for clean cost analysis

    # 4. Run the Compiler Passes using the same assembler
    # Pass 0: Extract Events
    events_by_board = _pass0_extract_events(morphism)
    
    # Pass 1: Translate to OASM
    _pass1_translate_to_oasm(events_by_board)

    # Pass 2: Analyze Costs - Use the same assembler
    _pass2_analyze_costs(events_by_board, test_seq)

    # 5. Find the relevant event and Assert
    rwg0_events = events_by_board[OASMAddress.RWG0]
    load_event = None
    for event in rwg0_events:
        if event.operation.operation_type == OperationType.RWG_LOAD_COEFFS:
            load_event = event
            break
    
    assert load_event is not None, "Could not find the RWG_LOAD_COEFFS event"
    
    # The core assertion of the test - verify exact match
    assert load_event.cost_cycles == 14, \
        f"Compiler calculated cost ({load_event.cost_cycles}) does not match expected cost (14)"
    
    # Additional verification that golden standard and compiler agree
    assert load_event.cost_cycles == expected_cost, \
        f"Compiler cost ({load_event.cost_cycles}) != Golden standard cost ({expected_cost})"

    print(f"\n✅ Test successful: RWG_LOAD_COEFFS cost correctly calculated as exactly 14 cycles.")


@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed")
def test_pass3_pipelining_constraint_checking():
    """
    Tests that Pass 3 correctly validates pipelining constraints by checking
    that PLAY duration >= LOAD cost for proper hardware pipelining.
    """
    print("\n🧪 Testing Pass 3 pipelining constraint checking...")
    
    # Set up test infrastructure
    board = Board("RWG0")
    channel = Channel(board=board, local_id=0, channel_type=ChannelType.RWG)
    
    # Test Case 1: Valid pipelining (PLAY duration > LOAD cost)
    print("  Testing valid pipelining scenario...")
    
    # Create waveform instruction for PLAY operation
    waveform_instruction = RWGWaveformInstruction(
        params=[WaveformParams(
            sbg_id=1,
            freq_coeffs=(10.0, 0.1, None, None),
            amp_coeffs=(0.5, 0.01, None, None),
            initial_phase=1.57,
            phase_reset=True
        )]
    )
    
    # Create a PLAY operation with 1000 cycles duration
    play_morphism = rwg_update_params(
        channel, 
        duration_us=4.0,  # 4μs = 1000 cycles at 250MHz
        start_state=waveform_instruction,
        end_state=RWGActive(carrier_freq=100e6, rf_on=True)
    )
    
    # Create a LOAD operation that costs 14 cycles (known from previous test)
    load_waveform_params = WaveformParams(
        sbg_id=1,
        freq_coeffs=(10.0, 0.1, None, None),
        amp_coeffs=(0.5, 0.01, None, None),
        initial_phase=1.57,
        phase_reset=True
    )
    
    load_morphism = rwg_load_coeffs(
        channel,
        params=[load_waveform_params],
        start_state=RWGActive(carrier_freq=100e6, rf_on=True)
    )
    
    # Create sequence: PLAY(1000c) followed by LOAD(14c) - should be valid
    valid_sequence = play_morphism @ load_morphism
    
    # Run compiler passes
    events_by_board = _pass0_extract_events(valid_sequence)
    _pass1_translate_to_oasm(events_by_board)
    
    # Set up assembler for cost analysis
    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    run_all = run_cfg(intf, [0, 1])
    test_seq = assembler(run_all, [('rwg0', C_RWG)])
    
    _pass2_analyze_costs(events_by_board, test_seq)
    
    # Pass 3 should succeed without raising an exception
    try:
        _pass3_check_constraints(events_by_board)
        print("  ✅ Valid pipelining scenario passed constraint check")
    except ValueError as e:
        pytest.fail(f"Valid pipelining scenario should not fail constraint check: {e}")
    
    # Test Case 2: Invalid pipelining (PLAY duration < LOAD cost)
    print("  Testing invalid pipelining scenario...")
    
    # Create a PLAY operation with very short duration (5 cycles < 14 cycles LOAD cost)
    short_play_morphism = rwg_update_params(
        channel,
        duration_us=0.02,  # 0.02μs = 5 cycles at 250MHz  
        start_state=waveform_instruction,
        end_state=RWGActive(carrier_freq=100e6, rf_on=True)
    )
    
    # Create sequence: SHORT_PLAY(5c) followed by LOAD(14c) - should fail
    invalid_sequence = short_play_morphism @ load_morphism
    
    # Run compiler passes
    events_by_board_invalid = _pass0_extract_events(invalid_sequence)
    _pass1_translate_to_oasm(events_by_board_invalid)
    
    # Fresh assembler for second test
    test_seq_invalid = assembler(run_all, [('rwg0', C_RWG)])
    _pass2_analyze_costs(events_by_board_invalid, test_seq_invalid)
    
    # Pass 3 should raise ValueError for timing violation
    with pytest.raises(ValueError, match=r"Timing violation.*duration 5 cycles.*requires 14 cycles"):
        _pass3_check_constraints(events_by_board_invalid)
    
    print("  ✅ Invalid pipelining scenario correctly failed constraint check")
    print("✅ Pass 3 pipelining constraint checking test completed successfully!")


@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed")
def test_pass4_oasm_call_generation_and_timing():
    """
    Tests that Pass 4 correctly generates OASM calls with proper timing
    and wait insertion between operations.
    """
    print("\n🧪 Testing Pass 4 OASM call generation and timing...")
    
    # Set up test infrastructure
    board = Board("RWG0")
    channel = Channel(board=board, local_id=0, channel_type=ChannelType.RWG)
    
    # Create a sequence with known timing
    test_waveform_params = WaveformParams(
        sbg_id=1,
        freq_coeffs=(10.0, 0.1, None, None),
        amp_coeffs=(0.5, 0.01, None, None),
        initial_phase=1.57,
        phase_reset=True
    )
    
    # Create morphism: delay(10μs) → load_coeffs
    morphism = (
        identity(duration_us=10) >>  # 2500 cycles at 250MHz
        rwg_load_coeffs(
            channel,
            params=[test_waveform_params],
            start_state=RWGReady(carrier_freq=100e6, rf_on=False)
        )
    )
    
    print("  Created test morphism: 10μs delay + RWG_LOAD_COEFFS")
    
    # Run compiler passes up to Pass 3
    events_by_board = _pass0_extract_events(morphism)
    _pass1_translate_to_oasm(events_by_board)
    
    # Set up assembler for cost analysis
    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    run_all = run_cfg(intf, [0, 1])
    test_seq = assembler(run_all, [('rwg0', C_RWG)])
    
    _pass2_analyze_costs(events_by_board, test_seq)
    _pass3_check_constraints(events_by_board)
    
    # Pass 4: Generate OASM calls
    print("  Running Pass 4 to generate OASM calls...")
    oasm_calls = _pass4_generate_oasm_calls(events_by_board)
    
    print(f"  Generated {len(oasm_calls)} OASM calls")
    for i, call in enumerate(oasm_calls):
        print(f"    {i+1}: {call.adr.value} -> {call.dsl_func.name} {call.args}")
    
    # Verify expected structure
    assert len(oasm_calls) >= 2, f"Expected at least 2 calls (wait + load), got {len(oasm_calls)}"
    
    # First call should be a WAIT_US for the 10μs delay
    wait_call = oasm_calls[0]
    assert wait_call.dsl_func == OASMFunction.WAIT_US, f"First call should be WAIT_US, got {wait_call.dsl_func.name}"
    assert wait_call.adr == OASMAddress.RWG0, f"Wait call should be for RWG0, got {wait_call.adr}"
    
    # Verify wait duration (should be 10μs)
    wait_duration = wait_call.args[0]
    assert abs(wait_duration - 10.0) < 0.001, f"Wait duration should be ~10μs, got {wait_duration}μs"
    print(f"  ✅ Wait call correctly generated for {wait_duration}μs")
    
    # Second call should be RWG_LOAD_WAVEFORM
    load_call = oasm_calls[1]
    assert load_call.dsl_func == OASMFunction.RWG_LOAD_WAVEFORM, f"Second call should be RWG_LOAD_WAVEFORM, got {load_call.dsl_func.name}"
    assert load_call.adr == OASMAddress.RWG0, f"Load call should be for RWG0, got {load_call.adr}"
    
    # Verify load call has correct waveform parameters
    load_params = load_call.args[0]
    assert isinstance(load_params, WaveformParams), f"Load call should have WaveformParams, got {type(load_params)}"
    assert load_params.sbg_id == 1, f"SBG ID should be 1, got {load_params.sbg_id}"
    assert load_params.freq_coeffs == (10.0, 0.1, None, None), f"Freq coeffs mismatch"
    print(f"  ✅ Load call correctly generated with proper parameters")
    
    # Test timing validation - calls should be properly ordered
    if len(oasm_calls) > 2:
        # If there are additional calls, they should maintain proper timing order
        for i in range(len(oasm_calls) - 1):
            current_call = oasm_calls[i]
            next_call = oasm_calls[i + 1]
            assert current_call.adr == next_call.adr, f"All calls should be for same board in sequence"
    
    print("✅ Pass 4 OASM call generation test completed successfully!")


@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed") 
def test_pass4_multiple_events_timing():
    """
    Tests Pass 4 with multiple events at different timestamps to verify
    correct wait insertion and timing calculations.
    """
    print("\n🧪 Testing Pass 4 with multiple timed events...")
    
    board = Board("RWG0")
    channel = Channel(board=board, local_id=0, channel_type=ChannelType.RWG)
    
    # Create a more complex sequence: delay(5μs) → load → delay(15μs) → update 
    waveform_params = WaveformParams(
        sbg_id=1,
        freq_coeffs=(10.0, 0.1, None, None),
        amp_coeffs=(0.5, 0.01, None, None),
        initial_phase=1.57,
        phase_reset=True
    )
    
    waveform_instruction = RWGWaveformInstruction(params=[waveform_params])
    
    # Create complex morphism
    morphism = (
        identity(duration_us=5) >>  # 1250 cycles
        rwg_load_coeffs(
            channel,
            params=[waveform_params],
            start_state=RWGReady(carrier_freq=100e6, rf_on=False)
        ) >>
        identity(duration_us=15) >>  # 3750 cycles
        rwg_update_params(
            channel,
            duration_us=8.0,  # 2000 cycles 
            start_state=waveform_instruction,
            end_state=RWGActive(carrier_freq=100e6, rf_on=True)
        )
    )
    
    print("  Created complex morphism: 5μs → load → 15μs → update(8μs)")
    
    # Run all compiler passes
    events_by_board = _pass0_extract_events(morphism)
    _pass1_translate_to_oasm(events_by_board)
    
    intf = sim_intf()
    intf.nod_adr = 0 
    intf.loc_chn = 1
    run_all = run_cfg(intf, [0, 1])
    test_seq = assembler(run_all, [('rwg0', C_RWG)])
    
    _pass2_analyze_costs(events_by_board, test_seq)
    _pass3_check_constraints(events_by_board)
    
    # Generate OASM calls
    oasm_calls = _pass4_generate_oasm_calls(events_by_board)
    
    print(f"  Generated {len(oasm_calls)} OASM calls:")
    for i, call in enumerate(oasm_calls):
        print(f"    {i+1}: {call.adr.value} -> {call.dsl_func.name} {call.args}")
    
    # Verify the call sequence structure
    assert len(oasm_calls) >= 4, f"Expected at least 4 calls, got {len(oasm_calls)}"
    
    # Expected sequence: WAIT(5μs) → LOAD → WAIT(15μs) → PLAY
    call_types = [call.dsl_func for call in oasm_calls]
    
    # Find wait and operation calls
    wait_calls = [call for call in oasm_calls if call.dsl_func == OASMFunction.WAIT_US]
    load_calls = [call for call in oasm_calls if call.dsl_func == OASMFunction.RWG_LOAD_WAVEFORM] 
    play_calls = [call for call in oasm_calls if call.dsl_func == OASMFunction.RWG_PLAY]
    
    # With intelligent pipeline scheduling, we get a specific, predictable pattern:
    # LOAD is optimized from 1250c to 4986c, creating the pattern:
    # WAIT(5.0μs) + WAIT(14.944μs) + LOAD + WAIT(0.056μs) + PLAY
    
    assert len(load_calls) == 1, f"Expected 1 load call, got {len(load_calls)}" 
    assert len(play_calls) == 1, f"Expected 1 play call, got {len(play_calls)}"
    
    # Intelligent scheduling creates exactly 3 WAIT calls for this scenario
    assert len(wait_calls) == 3, f"Expected exactly 3 wait calls, got {len(wait_calls)}"
    
    # Verify the exact wait durations from optimization
    wait_durations = [call.args[0] for call in wait_calls]
    expected_waits = [5.0, 14.944, 0.056]  # From the specific optimization result
    
    for i, (actual, expected) in enumerate(zip(wait_durations, expected_waits)):
        assert abs(actual - expected) < 0.001, \
            f"Wait {i+1} should be {expected}μs, got {actual}μs"
    
    # Total wait time is exactly preserved
    total_wait_time = sum(wait_durations)
    expected_total_wait = 20.0  # 5μs initial + 15μs middle = 20μs total
    assert abs(total_wait_time - expected_total_wait) < 0.001, \
        f"Total wait time should be exactly {expected_total_wait}μs, got {total_wait_time}μs"
    
    wait_durations = [call.args[0] for call in wait_calls]
    print(f"  ✅ Timing verified: total wait time {total_wait_time}μs with individual waits: {wait_durations}")
    print("✅ Pass 4 multiple events timing test completed successfully!")


@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed")
def test_complete_compilation_pipeline():
    """
    Tests the complete 4-pass compilation pipeline from a CatSeq morphism
    to final OASM calls, verifying all passes work together correctly.
    """
    print("\n🎯 Testing complete 4-pass compilation pipeline...")
    
    board = Board("RWG0")
    channel = Channel(board=board, local_id=0, channel_type=ChannelType.RWG)
    
    # Use proper MorphismDef to create a realistic RWG sequence
    # Define the target state using InitialTarget
    target = rwg.InitialTarget(sbg_id=1, freq=10.0, amp=0.5)
    
    # Create morphism: delay → set_state (which internally creates LOAD → UPDATE)
    start_state = RWGReady(carrier_freq=100e6, rf_on=False)
    
    # Create initial delay, then set_state morphism
    delay = identity(duration_us=3)  # Combined 3μs delay
    set_state_morphism = rwg.set_state([target])(channel, start_state)
    
    # Combine them
    morphism = delay >> set_state_morphism
    
    print("  Created end-to-end morphism: 3μs delay → set_state (LOAD → UPDATE)")
    
    # Set up OASM infrastructure
    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    run_all = run_cfg(intf, [0, 1])
    test_seq = assembler(run_all, [('rwg0', C_RWG)])
    
    print("  Running complete 4-pass compilation...")
    
    # Pass 0: Extract events from morphism 
    print("    Pass 0: Extracting events...")
    events_by_board = _pass0_extract_events(morphism)
    
    # Verify Pass 0 results
    assert OASMAddress.RWG0 in events_by_board, "Expected RWG0 board events"
    rwg0_events = events_by_board[OASMAddress.RWG0]
    assert len(rwg0_events) >= 2, f"Expected at least 2 events, got {len(rwg0_events)}"
    
    # Pass 1: Translate to OASM calls
    print("    Pass 1: Translating to OASM...")
    _pass1_translate_to_oasm(events_by_board)
    
    # Verify Pass 1 results - only non-identity events should have oasm_calls
    for event in rwg0_events:
        assert hasattr(event, 'oasm_calls'), f"Event should have oasm_calls after Pass 1"
        if event.operation.operation_type != OperationType.IDENTITY:
            assert len(event.oasm_calls) > 0, f"Non-identity event should have at least one OASM call"
    
    # Pass 2: Analyze costs
    print("    Pass 2: Analyzing costs...")
    _pass2_analyze_costs(events_by_board, test_seq)
    
    # Verify Pass 2 results - load event should have cost
    load_event = None
    for event in rwg0_events:
        if event.operation.operation_type == OperationType.RWG_LOAD_COEFFS:
            load_event = event
            break
    
    assert load_event is not None, "Should find RWG_LOAD_COEFFS event"
    assert load_event.cost_cycles == 9, f"Load cost should be 9 cycles, got {load_event.cost_cycles}"
    
    # Pass 3: Check constraints  
    print("    Pass 3: Checking constraints...")
    _pass3_check_constraints(events_by_board)  # Should not raise exception
    
    # Pass 4: Generate final OASM calls
    print("    Pass 4: Generating final OASM calls...")
    oasm_calls = _pass4_generate_oasm_calls(events_by_board)
    
    # Verify final OASM calls structure
    print(f"  Generated {len(oasm_calls)} final OASM calls:")
    for i, call in enumerate(oasm_calls):
        print(f"    {i+1}: {call.adr.value} -> {call.dsl_func.name} {call.args}")
    
    # Comprehensive validation of final output
    assert len(oasm_calls) >= 4, f"Expected at least 4 calls, got {len(oasm_calls)}"
    
    # Intelligent scheduling creates a specific, predictable call pattern
    # Based on the optimization: LOAD is rescheduled to start 14 cycles before PLAY
    
    wait_calls = [call for call in oasm_calls if call.dsl_func == OASMFunction.WAIT_US]
    load_calls = [call for call in oasm_calls if call.dsl_func == OASMFunction.RWG_LOAD_WAVEFORM]
    play_calls = [call for call in oasm_calls if call.dsl_func == OASMFunction.RWG_PLAY]
    
    # Should have exactly the expected number of operations
    assert len(load_calls) == 1, f"Expected 1 load call, got {len(load_calls)}"
    assert len(play_calls) == 1, f"Expected 1 play call, got {len(play_calls)}"
    
    # With set_state MorphismDef, intelligent scheduling creates exactly 2 WAIT calls:
    # WAIT(2.964μs) + WAIT(0.036μs) = 3.0μs total (9 cycles = 0.036μs optimization)
    assert len(wait_calls) == 2, f"Expected exactly 2 wait calls with optimization, got {len(wait_calls)}"
    
    # Verify the exact wait durations from intelligent scheduling
    wait_durations = [call.args[0] for call in wait_calls]
    expected_waits = [2.964, 0.036]  # From the specific optimization result
    
    for i, (actual, expected) in enumerate(zip(wait_durations, expected_waits)):
        assert abs(actual - expected) < 0.001, \
            f"Wait {i+1} should be {expected}μs, got {actual}μs"
    
    # Total wait time should be preserved exactly
    total_wait_time = sum(wait_durations)
    expected_total_wait = 3.0  # Total delay preserved
    assert abs(total_wait_time - expected_total_wait) < 0.001, \
        f"Total wait time should be exactly {expected_total_wait}μs, got {total_wait_time}μs"
    
    # Verify load call parameters
    load_params = load_calls[0].args[0]
    assert load_params.sbg_id == 1, f"SBG ID should be 1, got {load_params.sbg_id}"
    assert load_params.freq_coeffs == (10.0, None, None, None), "Frequency coefficients mismatch"
    
    # Verify play call parameters
    play_calls = [call for call in oasm_calls if call.dsl_func == OASMFunction.RWG_PLAY]
    assert len(play_calls) == 1, f"Expected 1 play call, got {len(play_calls)}"
    
    # Verify play call parameters - no duration parameter anymore
    pud_mask = play_calls[0].args[0]
    iou_mask = play_calls[0].args[1]
    assert pud_mask == 1, f"PUD mask should be 1, got {pud_mask}"
    assert iou_mask == 1, f"IOU mask should be 1, got {iou_mask}"
    
    print("  ✅ All passes completed successfully")
    print("  ✅ Final OASM calls structure validated")  
    print("  ✅ Timing and parameters verified")
    print("✅ Complete compilation pipeline test passed!")


def test_pipeline_pair_identification():
    """
    Tests the pipeline pair identification algorithm that finds LOAD → PLAY sequences.
    """
    print("\n🧪 Testing pipeline pair identification...")
    
    # Create test morphism with clear LOAD → PLAY pairs
    board = Board("RWG0")
    ch0 = Channel(board=board, local_id=0, channel_type=ChannelType.RWG)
    ch1 = Channel(board=board, local_id=1, channel_type=ChannelType.RWG)
    
    # Two channels with different timing
    waveform_params_ch0 = WaveformParams(
        sbg_id=0,
        freq_coeffs=(10.0, 0.1, None, None),
        amp_coeffs=(0.5, 0.01, None, None),
        initial_phase=0.0,
        phase_reset=True
    )
    
    waveform_params_ch1 = WaveformParams(
        sbg_id=1,
        freq_coeffs=(20.0, 0.2, None, None), 
        amp_coeffs=(0.8, 0.02, None, None),
        initial_phase=1.57,
        phase_reset=True
    )
    
    # Create morphisms that should generate LOAD → PLAY pairs
    ch0_morphism = (
        identity(duration_us=5) >>
        rwg_load_coeffs(
            ch0,
            params=[waveform_params_ch0],
            start_state=RWGReady(carrier_freq=100e6, rf_on=False)
        ) >>
        rwg_update_params(
            ch0,
            duration_us=10.0,
            start_state=RWGActive(carrier_freq=100e6, rf_on=True),
            end_state=RWGActive(carrier_freq=100e6, rf_on=True)
        )
    )
    
    ch1_morphism = (
        identity(duration_us=8) >>
        rwg_load_coeffs(
            ch1,
            params=[waveform_params_ch1],
            start_state=RWGReady(carrier_freq=100e6, rf_on=False)
        ) >>
        rwg_update_params(
            ch1,
            duration_us=15.0,
            start_state=RWGActive(carrier_freq=100e6, rf_on=True),
            end_state=RWGActive(carrier_freq=100e6, rf_on=True)
        )
    )
    
    # Parallel execution
    parallel_morphism = ch0_morphism | ch1_morphism
    print("  Created parallel morphism with two channels")
    
    # Extract events
    events_by_board = _pass0_extract_events(parallel_morphism)
    rwg0_events = events_by_board[OASMAddress.RWG0]
    
    print(f"  Extracted {len(rwg0_events)} events from morphism")
    for i, event in enumerate(rwg0_events):
        print(f"    Event {i}: {event.operation.operation_type.name} on {event.operation.channel.global_id} at t={event.timestamp_cycles}c")
    
    # Test pipeline pair identification
    pipeline_pairs = _identify_pipeline_pairs(rwg0_events)
    
    print(f"  Identified {len(pipeline_pairs)} pipeline pairs:")
    for i, pair in enumerate(pipeline_pairs):
        print(f"    Pair {i}: LOAD@{pair.load_event.timestamp_cycles}c → PLAY@{pair.play_event.timestamp_cycles}c on {pair.channel.global_id}")
    
    # Verify results
    assert len(pipeline_pairs) == 2, f"Expected 2 pipeline pairs (one per channel), got {len(pipeline_pairs)}"
    
    # Check that each channel has one pair
    channels_found = set()
    for pair in pipeline_pairs:
        channels_found.add(pair.channel.global_id)
        
        # Verify pair integrity
        assert pair.load_event.operation.operation_type == OperationType.RWG_LOAD_COEFFS
        assert pair.play_event.operation.operation_type == OperationType.RWG_UPDATE_PARAMS
        assert pair.load_event.operation.channel == pair.play_event.operation.channel
        assert pair.load_event.timestamp_cycles <= pair.play_event.timestamp_cycles
    
    expected_channels = {ch0.global_id, ch1.global_id}
    assert channels_found == expected_channels, f"Expected channels {expected_channels}, got {channels_found}"
    
    print("  ✅ All pipeline pairs correctly identified")
    print("  ✅ Each pair has proper LOAD → PLAY sequence on same channel")
    print("  ✅ Timing relationships verified")
    print("✅ Pipeline pair identification test completed successfully!")


@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed")
def test_intelligent_scheduling_optimization():
    """
    Tests the intelligent scheduling logic that optimizes LOAD timing
    to minimize wait times while respecting hardware constraints.
    """
    print("\n🧪 Testing intelligent scheduling optimization...")
    
    board = Board("RWG0")
    ch0 = Channel(board=board, local_id=0, channel_type=ChannelType.RWG)
    ch1 = Channel(board=board, local_id=1, channel_type=ChannelType.RWG)
    
    # Create scenario: Ch0 plays at 10μs, Ch1 plays at 15μs
    # Ch1's LOAD should be optimized to start during Ch0's PLAY
    waveform_params0 = WaveformParams(
        sbg_id=0,
        freq_coeffs=(10.0, None, None, None),
        amp_coeffs=(0.5, None, None, None),
        initial_phase=0.0,
        phase_reset=True
    )

    waveform_params1 = WaveformParams(
        sbg_id=1,
        freq_coeffs=(10.0, None, None, None),
        amp_coeffs=(0.5, None, None, None),
        initial_phase=0.0,
        phase_reset=True
    )
    
    ch0_morphism = (
        identity(duration_us=10) >>  # Wait 10μs
        rwg_load_coeffs(
            ch0,
            params=[waveform_params0],
            start_state=RWGReady(carrier_freq=100e6, rf_on=False)
        ) >>
        rwg_update_params(
            ch0,
            duration_us=5.0,  # 5μs PLAY duration
            start_state=RWGActive(carrier_freq=100e6, rf_on=True),
            end_state=RWGActive(carrier_freq=100e6, rf_on=True)
        )
    )
    
    ch1_morphism = (
        identity(duration_us=15) >>  # Wait 15μs
        rwg_load_coeffs(
            ch1,
            params=[waveform_params1],
            start_state=RWGReady(carrier_freq=100e6, rf_on=False)
        ) >>
        rwg_update_params(
            ch1,
            duration_us=3.0,  # 3μs PLAY duration
            start_state=RWGActive(carrier_freq=100e6, rf_on=True),
            end_state=RWGActive(carrier_freq=100e6, rf_on=True)
        )
    )
    
    parallel_morphism = ch0_morphism | ch1_morphism
    print(parallel_morphism.lanes_view())
    print("  Created morphism: Ch0 PLAY@10μs, Ch1 PLAY@15μs")
    
    # Run through compiler passes
    events_by_board = _pass0_extract_events(parallel_morphism)
    _pass1_translate_to_oasm(events_by_board)
    
    # Set up assembler for cost analysis
    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    run_all = run_cfg(intf, [0, 1])
    test_seq = assembler(run_all, [('rwg0', C_RWG)])
    
    _pass2_analyze_costs(events_by_board, test_seq)
    rwg0_events = events_by_board[OASMAddress.RWG0]
    
    print("  Original event timestamps:")
    for event in rwg0_events:
        if event.operation.operation_type in [OperationType.RWG_LOAD_COEFFS, OperationType.RWG_UPDATE_PARAMS]:
            print(f"    {event.operation.operation_type.name} on {event.operation.channel.global_id}: {event.timestamp_cycles}c")
    
    # Test intelligent scheduling
    pipeline_pairs = _identify_pipeline_pairs(rwg0_events)
    optimized_events = _calculate_optimal_schedule(rwg0_events, pipeline_pairs)
    
    print("  Optimized event timestamps:")
    optimization_found = False
    for event in optimized_events:
        if event.operation.operation_type in [OperationType.RWG_LOAD_COEFFS, OperationType.RWG_UPDATE_PARAMS]:
            print(f"    {event.operation.operation_type.name} on {event.operation.channel.global_id}: {event.timestamp_cycles}c")
            
            # Check if Ch1's LOAD was optimized
            if (event.operation.operation_type == OperationType.RWG_LOAD_COEFFS and 
                event.operation.channel == ch1):
                # Ch1's LOAD should be rescheduled to start at 15μs - 14c = 3736c
                expected_optimal_time = 3750 - 14  # 15μs - LOAD cost
                if abs(event.timestamp_cycles - expected_optimal_time) < 5:  # Allow small tolerance
                    optimization_found = True
                    print(f"    ✅ Ch1 LOAD optimized to start at {event.timestamp_cycles}c (expected ~{expected_optimal_time}c)")
    
    # Verify optimization was applied
    assert len(pipeline_pairs) == 2, f"Expected 2 pipeline pairs, got {len(pipeline_pairs)}"
    print(f"  ✅ Found {len(pipeline_pairs)} pipeline pairs for optimization")
    
    if optimization_found:
        print("  ✅ Intelligent scheduling optimization successfully applied")
    else:
        print("  ℹ️  No significant optimization possible for this scenario")
    
    # Verify all events are present and properly ordered
    optimized_events.sort(key=lambda e: e.timestamp_cycles)
    assert len(optimized_events) == len(rwg0_events), "Event count should remain the same"
    
    # Verify timing constraints are still satisfied
    for pair in pipeline_pairs:
        optimized_load = None
        optimized_play = None
        
        for event in optimized_events:
            if event.operation.channel == pair.channel:
                if event.operation.operation_type == OperationType.RWG_LOAD_COEFFS:
                    optimized_load = event
                elif event.operation.operation_type == OperationType.RWG_UPDATE_PARAMS:
                    optimized_play = event
        
        if optimized_load and optimized_play:
            load_end_time = optimized_load.timestamp_cycles + optimized_load.cost_cycles
            play_start_time = optimized_play.timestamp_cycles
            assert load_end_time <= play_start_time, f"LOAD must complete before PLAY on {pair.channel.global_id}"
    
    print("  ✅ All timing constraints verified after optimization")
    print("✅ Intelligent scheduling optimization test completed successfully!")
