"""
Integration tests for global synchronization in the compiler.

Tests multi-board synchronization, rwg_init constraints, and dynamic timing calculations.
"""

import pytest

from catseq.types.common import Board, Channel, ChannelType, OperationType
from catseq.compilation.types import OASMAddress, OASMFunction
from catseq.types.rwg import WaveformParams
from catseq.hardware import rwg
from catseq.hardware.sync import global_sync
from catseq.compilation.compiler import compile_to_oasm_calls

# OASM imports for assembler setup
try:
    from oasm.rtmq2 import assembler
    from oasm.dev.rwg import C_RWG
    from oasm.rtmq2.intf import sim_intf
    from oasm.dev.main import run_cfg
    OASM_AVAILABLE = True
except ImportError:
    OASM_AVAILABLE = False


@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed")
def test_multi_board_global_sync():
    """
    Tests that multi-board sequences trigger global synchronization.
    """
    # 1. Arrange - Create sequences on different boards
    main_board = Board("main")
    rwg0_board = Board("rwg0") 
    rwg1_board = Board("rwg1")
    
    main_ch = Channel(main_board, 0, ChannelType.RWG)
    rwg0_ch = Channel(rwg0_board, 0, ChannelType.RWG) 
    rwg1_ch = Channel(rwg1_board, 0, ChannelType.RWG)
    
    # Create initial morphism with all boards
    init_morphism = (
        rwg.initialize(carrier_freq=100.0)(main_ch) |
        rwg.initialize(carrier_freq=150.0)(rwg0_ch) |
        rwg.initialize(carrier_freq=200.0)(rwg1_ch)
    )
    
    # Apply global sync to all channels using >> operator
    from catseq.hardware.sync import global_sync
    
    multi_board_sequence = init_morphism >> global_sync(12345)
    
    # Set up assembler
    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    rwgs = [0, 1, 2]  # 3 boards
    run_all = run_cfg(intf, rwgs)
    assembler_seq = assembler(run_all, [('rwg0', C_RWG), ('rwg1', C_RWG), ('main', C_RWG)])
    
    # 2. Act
    calls_by_board = compile_to_oasm_calls(multi_board_sequence, assembler_seq)
    
    # 3. Assert - Verify global sync structure
    print("OASM calls by board:")
    for board_adr, calls in calls_by_board.items():
        print(f"  {board_adr.value}: {[call.dsl_func.name for call in calls]}")
    
    # Verify expected boards are present
    assert OASMAddress.MAIN in calls_by_board
    assert OASMAddress.RWG0 in calls_by_board
    assert OASMAddress.RWG1 in calls_by_board
    
    # Verify sync operations on each board
    main_calls = calls_by_board[OASMAddress.MAIN]
    rwg0_calls = calls_by_board[OASMAddress.RWG0] 
    rwg1_calls = calls_by_board[OASMAddress.RWG1]
    
    # Master board should have TRIG_SLAVE
    main_funcs = [call.dsl_func for call in main_calls]
    assert OASMFunction.TRIG_SLAVE in main_funcs, "Master board missing TRIG_SLAVE operation"
    
    # Slave boards should have WAIT_MASTER
    rwg0_funcs = [call.dsl_func for call in rwg0_calls]
    rwg1_funcs = [call.dsl_func for call in rwg1_calls]
    assert OASMFunction.WAIT_MASTER in rwg0_funcs, "RWG0 slave board missing WAIT_MASTER operation"
    assert OASMFunction.WAIT_MASTER in rwg1_funcs, "RWG1 slave board missing WAIT_MASTER operation"
    
    total_calls = sum(len(calls) for calls in calls_by_board.values())
    print(f"Global sync test passed: {total_calls} OASM calls generated across {len(calls_by_board)} boards")


@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed")
def test_rwg_init_constraint_violation():
    """
    Tests that rwg_init operations after global sync trigger an error.
    """
    # 1. Arrange - Create a sequence that would violate the constraint
    main_board = Board("main")
    rwg0_board = Board("rwg0")
    
    main_ch = Channel(main_board, 0, ChannelType.RWG)
    rwg0_ch = Channel(rwg0_board, 0, ChannelType.RWG)
    
    # Main board initializes early, rwg0 tries to initialize late
    main_seq = (
        rwg.initialize(carrier_freq=100.0) >>
        rwg.hold(200.0) >>  # Long delay to push sync point later
        rwg.set_state([rwg.InitialTarget(sbg_id=0, freq=10, amp=0.5)])
    )
    
    # rwg0 tries to initialize after a very long delay - this should fail
    rwg0_seq = (
        rwg.hold(300.0) >>  # This delay might push init past global sync
        rwg.initialize(carrier_freq=150.0) >>
        rwg.set_state([rwg.InitialTarget(sbg_id=0, freq=20, amp=0.8)])
    )
    
    multi_board_sequence = main_seq(main_ch) | rwg0_seq(rwg0_ch)
    
    # Set up assembler
    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    rwgs = [0, 1]
    run_all = run_cfg(intf, rwgs)
    assembler_seq = assembler(run_all, [('rwg0', C_RWG), ('main', C_RWG)])
    
    # 2. Act & Assert - Should raise constraint violation
    with pytest.raises(ValueError, match="RWG_INIT.*must occur before global sync"):
        compile_to_oasm_calls(multi_board_sequence, assembler_seq)


@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed")
def test_dynamic_master_wait_calculation():
    """
    Tests that master wait time is dynamically calculated based on slave operations.
    """
    # 1. Arrange - Create sequences with different pre-sync costs
    main_board = Board("main")
    rwg0_board = Board("rwg0")
    rwg1_board = Board("rwg1")
    
    main_ch = Channel(main_board, 0, ChannelType.RWG)
    rwg0_ch = Channel(rwg0_board, 0, ChannelType.RWG)
    rwg1_ch = Channel(rwg1_board, 0, ChannelType.RWG)
    
    # Main board - minimal pre-sync work
    main_seq = (
        rwg.initialize(carrier_freq=100.0) >>
        rwg.set_state([rwg.InitialTarget(sbg_id=0, freq=10, amp=0.5)])
    )
    
    # rwg0 - moderate pre-sync work
    rwg0_seq = (
        rwg.initialize(carrier_freq=150.0) >>
        rwg.hold(50.0) >>
        rwg.set_state([rwg.InitialTarget(sbg_id=0, freq=20, amp=0.8)])
    )
    
    # rwg1 - heavy pre-sync work (should determine master wait time)
    rwg1_seq = (
        rwg.initialize(carrier_freq=200.0) >>
        rwg.hold(150.0) >>  # Longest delay
        rwg.set_state([rwg.InitialTarget(sbg_id=0, freq=30, amp=0.6)]) >>
        rwg.set_state([rwg.InitialTarget(sbg_id=1, freq=35, amp=0.7)])  # Additional work
    )
    
    multi_board_sequence = (main_seq(main_ch) | rwg0_seq(rwg0_ch) | rwg1_seq(rwg1_ch)) >> global_sync(12345)
    
    # Set up assembler
    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    rwgs = [0, 1, 2]
    run_all = run_cfg(intf, rwgs)
    assembler_seq = assembler(run_all, [('rwg0', C_RWG), ('rwg1', C_RWG), ('main', C_RWG)])
    
    # 2. Act
    oasm_calls = compile_to_oasm_calls(multi_board_sequence, assembler_seq)
    
    # 3. Assert - Find WAIT_MASTER calls and verify they have reasonable duration
    wait_master_calls = []
    trig_slave_calls = []
    for board_calls in oasm_calls.values():
        for call in board_calls:
            if call.dsl_func == OASMFunction.WAIT_MASTER:
                wait_master_calls.append(call)
            elif call.dsl_func == OASMFunction.TRIG_SLAVE:
                trig_slave_calls.append(call)
    
    # Should have 2 WAIT_MASTER calls (rwg0, rwg1) and 1 TRIG_SLAVE call (main)
    assert len(wait_master_calls) == 2, f"Expected 2 WAIT_MASTER calls, got {len(wait_master_calls)}"
    assert len(trig_slave_calls) == 1, f"Expected 1 TRIG_SLAVE call, got {len(trig_slave_calls)}"
    
    # The wait_time should be in the TRIG_SLAVE call (first argument), not WAIT_MASTER
    trig_slave_call = trig_slave_calls[0]  
    wait_time_cycles = trig_slave_call.args[0]  # First argument is wait_time in cycles
    wait_duration_us = wait_time_cycles / 250.0  # Convert to microseconds
    
    # Wait duration should be significant (more than just safety margin)
    # rwg0 has 50μs hold, so should be around 50μs + safety margin
    expected_min_duration = 40.0  # At least most of the hold duration
    assert wait_duration_us >= expected_min_duration, f"Wait duration {wait_duration_us:.1f}μs too short"
    
    # But shouldn't be excessive (with safety margin, should be < 80μs)  
    assert wait_duration_us < 80.0, f"Wait duration {wait_duration_us:.1f}μs too long"
    
    print(f"Dynamic wait calculation test passed: master waits {wait_duration_us:.1f}μs")


@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed")  
def test_single_board_no_sync():
    """
    Tests that single-board sequences don't generate global sync calls.
    """
    # 1. Arrange - Single board sequence
    board = Board("rwg0")
    ch = Channel(board, 0, ChannelType.RWG)
    
    sequence = (
        rwg.initialize(carrier_freq=100.0) >>
        rwg.hold(50.0) >>
        rwg.set_state([rwg.InitialTarget(sbg_id=0, freq=10, amp=0.5)]) >>
        rwg.linear_ramp([rwg.RampTarget(target_freq=20, target_amp=0.8)], duration_us=10)
    )
    
    single_board_morphism = sequence(ch)
    
    # Set up assembler
    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    rwgs = [0]
    run_all = run_cfg(intf, rwgs)
    assembler_seq = assembler(run_all, [('rwg0', C_RWG)])
    
    # 2. Act
    oasm_calls = compile_to_oasm_calls(single_board_morphism, assembler_seq)
    
    # 3. Assert - No global sync functions should be present
    all_calls = []
    for board_calls in oasm_calls.values():
        all_calls.extend(board_calls)
    func_sequence = [call.dsl_func for call in all_calls]
    
    assert OASMFunction.WAIT_MASTER not in func_sequence
    assert OASMFunction.TRIG_SLAVE not in func_sequence
    
    # Should still have normal RWG operations
    assert OASMFunction.RWG_INIT in func_sequence
    assert OASMFunction.RWG_LOAD_WAVEFORM in func_sequence
    assert OASMFunction.RWG_PLAY in func_sequence
    
    print(f"Single board test passed: {len(oasm_calls)} OASM calls, no sync needed")


@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed")
def test_global_sync_timing_accuracy():
    """
    Tests the accuracy of global sync timing calculations.
    """
    # 1. Arrange - Precise timing scenario
    main_board = Board("main")
    rwg0_board = Board("rwg0")
    
    main_ch = Channel(main_board, 0, ChannelType.RWG)
    rwg0_ch = Channel(rwg0_board, 0, ChannelType.RWG)
    
    # Main board - exactly 100μs of pre-sync work
    main_seq = (
        rwg.initialize(carrier_freq=100.0) >>
        rwg.hold(100.0) >>
        rwg.set_state([rwg.InitialTarget(sbg_id=0, freq=10, amp=0.5)])
    )
    
    # rwg0 - exactly 80μs of pre-sync work (should finish 20μs before main)
    rwg0_seq = (
        rwg.initialize(carrier_freq=150.0) >>
        rwg.hold(80.0) >>
        rwg.set_state([rwg.InitialTarget(sbg_id=0, freq=20, amp=0.8)])
    )
    
    multi_board_sequence = (main_seq(main_ch) | rwg0_seq(rwg0_ch)) >> global_sync(12345)
    
    # Set up assembler
    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    rwgs = [0, 1]
    run_all = run_cfg(intf, rwgs)
    assembler_seq = assembler(run_all, [('rwg0', C_RWG), ('main', C_RWG)])
    
    # 2. Act
    oasm_calls = compile_to_oasm_calls(multi_board_sequence, assembler_seq)
    
    # 3. Assert - Verify timing relationships
    # Find events around the sync point
    sync_events = []
    for board_calls in oasm_calls.values():
        for call in board_calls:
            if call.dsl_func in [OASMFunction.WAIT_MASTER, OASMFunction.TRIG_SLAVE]:
                sync_events.append(call)
    
    assert len(sync_events) == 2  # One WAIT_MASTER, one TRIG_SLAVE
    
    # The timing should account for the difference in pre-sync work
    # Master should wait approximately (100μs - 80μs) = 20μs + safety margin
    wait_master_call = next(call for call in sync_events if call.dsl_func == OASMFunction.WAIT_MASTER)
    wait_duration = wait_master_call.args[0]
    
    # Should be around 20μs plus safety margin (total ~25-30μs)
    assert 20.0 <= wait_duration <= 35.0, f"Wait duration {wait_duration} not in expected range"
    
    print(f"Timing accuracy test passed: master waits {wait_duration}μs (expected ~20-30μs)")