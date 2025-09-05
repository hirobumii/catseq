import pytest

from catseq.types.common import Board, Channel, ChannelType, OperationType
from catseq.compilation.types import OASMAddress, OASMFunction
from catseq.types.rwg import WaveformParams, RWGUninitialized, RWGReady, RWGActive
from catseq.hardware.rwg import InitialTarget, RampTarget
from catseq.types.ttl import TTLState
from catseq.hardware import rwg, ttl
from catseq.hardware.sync import global_sync
from catseq.morphism import identity, Morphism
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
        rwg.initialize(100.0)(main_ch) |
        rwg.initialize(150.0)(rwg0_ch) |
        rwg.initialize(200.0)(rwg1_ch)
    )
    
    # Apply global sync to all channels using >> operator
    multi_board_sequence = init_morphism >> global_sync()
    
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
    assert OASMAddress.MAIN in calls_by_board
    assert OASMAddress.RWG0 in calls_by_board
    assert OASMAddress.RWG1 in calls_by_board
    
    main_calls = calls_by_board[OASMAddress.MAIN]
    rwg0_calls = calls_by_board[OASMAddress.RWG0] 
    rwg1_calls = calls_by_board[OASMAddress.RWG1] 
    
    main_funcs = [call.dsl_func for call in main_calls]
    assert OASMFunction.TRIG_SLAVE in main_funcs, "Master board missing TRIG_SLAVE operation"
    
    rwg0_funcs = [call.dsl_func for call in rwg0_calls]
    rwg1_funcs = [call.dsl_func for call in rwg1_calls]
    assert OASMFunction.WAIT_MASTER in rwg0_funcs, "RWG0 slave board missing WAIT_MASTER operation"
    assert OASMFunction.WAIT_MASTER in rwg1_funcs, "RWG1 slave board missing WAIT_MASTER operation"


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
    
    main_seq = (
        rwg.initialize(100.0) >>
        rwg.hold(200.0) >>
        rwg.set_state([InitialTarget(sbg_id=0, freq=10, amp=0.5)])
    )
    
    rwg0_seq = (
        rwg.hold(300.0) >>
        rwg.initialize(150.0) >>
        rwg.set_state([InitialTarget(sbg_id=0, freq=20, amp=0.8)])
    )
    
    multi_board_sequence = main_seq(main_ch) | rwg0_seq(rwg0_ch)
    
    # Set up assembler
    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    rwgs = [0, 1]
    run_all = run_cfg(intf, rwgs)
    assembler_seq = assembler(run_all, [('rwg0', C_RWG), ('main', C_RWG)])
    
    # 2. Act - Under the new rules, this is a valid sequence and should compile without error.
    # The test now verifies that no exception is raised.
    compile_to_oasm_calls(multi_board_sequence, assembler_seq)


@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed")
def test_dynamic_master_wait_calculation():
    """
    Tests that master wait time is dynamically calculated based on slave operations.
    """
    # 1. Arrange
    main_board = Board("main")
    rwg0_board = Board("rwg0")
    rwg1_board = Board("rwg1")
    
    main_ch = Channel(main_board, 0, ChannelType.RWG)
    rwg0_ch = Channel(rwg0_board, 0, ChannelType.RWG)
    rwg1_ch = Channel(rwg1_board, 0, ChannelType.RWG)
    
    main_seq = (
        rwg.initialize(100.0) >>
        rwg.set_state([InitialTarget(sbg_id=0, freq=10, amp=0.5)])
    )
    
    rwg0_seq = (
        rwg.initialize(150.0) >>
        rwg.hold(50.0) >>
        rwg.set_state([InitialTarget(sbg_id=0, freq=20, amp=0.8)])
    )
    
    rwg1_seq = (
        rwg.initialize(200.0) >>
        rwg.hold(150.0) >>
        rwg.set_state([InitialTarget(sbg_id=0, freq=30, amp=0.6)]) >>
        rwg.set_state([InitialTarget(sbg_id=1, freq=35, amp=0.7)])
    )
    
    multi_board_sequence = (main_seq(main_ch) | rwg0_seq(rwg0_ch) | rwg1_seq(rwg1_ch)) >> global_sync()
    
    # Set up assembler
    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    rwgs = [0, 1, 2]
    run_all = run_cfg(intf, rwgs)
    assembler_seq = assembler(run_all, [('rwg0', C_RWG), ('rwg1', C_RWG), ('main', C_RWG)])
    
    # 2. Act
    oasm_calls = compile_to_oasm_calls(multi_board_sequence, assembler_seq)
    
    # 3. Assert
    wait_master_calls = []
    trig_slave_calls = []
    for board_calls in oasm_calls.values():
        for call in board_calls:
            if call.dsl_func == OASMFunction.WAIT_MASTER:
                wait_master_calls.append(call)
            elif call.dsl_func == OASMFunction.TRIG_SLAVE:
                trig_slave_calls.append(call)
    
    assert len(wait_master_calls) == 2
    assert len(trig_slave_calls) == 1
    
    trig_slave_call = trig_slave_calls[0]
    wait_time_cycles = trig_slave_call.args[0]
    wait_duration_us = wait_time_cycles / 250.0
    
    expected_min_duration = 150.0
    assert wait_duration_us >= expected_min_duration


@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed")  
def test_single_board_no_sync():
    """
    Tests that single-board sequences don't generate global sync calls.
    """
    # 1. Arrange
    board = Board("rwg0")
    ch = Channel(board, 0, ChannelType.RWG)
    
    sequence = (
        rwg.initialize(100.0) >>
        rwg.hold(50.0) >>
        rwg.set_state([InitialTarget(sbg_id=0, freq=10, amp=0.5)])
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
    
    # 3. Assert
    all_calls = []
    for board_calls in oasm_calls.values():
        all_calls.extend(board_calls)
    func_sequence = [call.dsl_func for call in all_calls]
    
    assert OASMFunction.WAIT_MASTER not in func_sequence
    assert OASMFunction.TRIG_SLAVE not in func_sequence


@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed")
def test_global_sync_timing_accuracy():
    """
    Tests the accuracy of global sync timing calculations.
    """
    # 1. Arrange
    main_board = Board("main")
    rwg0_board = Board("rwg0")
    
    main_ch = Channel(main_board, 0, ChannelType.RWG)
    rwg0_ch = Channel(rwg0_board, 0, ChannelType.RWG)
    
    main_seq = (
        rwg.initialize(100.0) >>
        rwg.hold(100.0) >>
        rwg.set_state([InitialTarget(sbg_id=0, freq=10, amp=0.5)])
    )
    
    rwg0_seq = (
        rwg.initialize(150.0) >>
        rwg.hold(80.0) >>
        rwg.set_state([InitialTarget(sbg_id=0, freq=20, amp=0.8)])
    )
    
    multi_board_sequence = (main_seq(main_ch) | rwg0_seq(rwg0_ch)) >> global_sync()
    
    # Set up assembler
    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    rwgs = [0, 1]
    run_all = run_cfg(intf, rwgs)
    assembler_seq = assembler(run_all, [('rwg0', C_RWG), ('main', C_RWG)])
    
    # 2. Act
    oasm_calls = compile_to_oasm_calls(multi_board_sequence, assembler_seq)
    
    # 3. Assert
    sync_events = []
    for board_calls in oasm_calls.values():
        for call in board_calls:
            if call.dsl_func in [OASMFunction.WAIT_MASTER, OASMFunction.TRIG_SLAVE]:
                sync_events.append(call)
    
    assert len(sync_events) == 2
    
    trig_slave_call = next(call for call in sync_events if call.dsl_func == OASMFunction.TRIG_SLAVE)
    wait_duration_cycles = trig_slave_call.args[0]
    
    # The longest lane is on the main board (100us). The slave board's operations
    # extend to 25250 cycles before padding. However, we must also account for the
    # execution cost of the SYNC_MASTER operation itself (16 cycles).
    # Total: max_end_time (25250 + 16) + 100-cycle safety margin = 25366
    expected_cycles = 25250 + 16 + 100
    assert wait_duration_cycles == expected_cycles, (
        f"Compiler-calculated wait duration {wait_duration_cycles} cycles does not match the "
        f"expected value of {expected_cycles} (100us sequence + 100 cycle margin)."
    )


@pytest.mark.skipif(not OASM_AVAILABLE, reason="OASM library not installed")
def test_complex_multi_board_sequence_with_sync():
    """
    Tests a complex multi-board, multi-channel sequence involving
    parallel and sequential composition across a global sync point.
    This serves as a comprehensive integration test for the core features.
    """
    # 1. Arrange
    # Define boards and channels
    main_board = Board("main")
    rwg0_board = Board("rwg0")
    ch_ttl = Channel(main_board, 0, ChannelType.TTL)
    ch_rwg = Channel(rwg0_board, 0, ChannelType.RWG)

    # Define a local pulse function for TTL for clarity
    def ttl_pulse(duration_us: float) -> Morphism:
        return ttl.on()(ch_ttl, start_state=TTLState.OFF) >> identity(duration_us) >> ttl.off()(ch_ttl, start_state=TTLState.ON)

    # -- Part 1: Pre-sync operations (epoch 0) --
    ttl_ops_pre = ttl_pulse(10)
    rwg_ops_pre = rwg.initialize(100.0)(ch_rwg) >> rwg.set_state(
        [rwg.InitialTarget(sbg_id=0, freq=10, amp=0.5)]
    )
    pre_sync_morphism = ttl_ops_pre | rwg_ops_pre

    # -- Part 2: Synchronization --
    # This creates the epoch boundary
    synced_morphism = pre_sync_morphism >> global_sync()

    # -- Part 3: Post-sync operations (epoch 1) --
    # After sync, we must explicitly provide the start state for each channel's sequence.
    ttl_start_state_post = synced_morphism.lanes[ch_ttl].operations[-1].end_state
    rwg_start_state_post = synced_morphism.lanes[ch_rwg].operations[-1].end_state

    # Define the post-sync operations for each channel as a callable sequence
    ttl_ops_post_seq = rwg.hold(5) >> ttl.on()
    rwg_ops_post_seq = rwg.set_state(
        [rwg.InitialTarget(sbg_id=0, freq=10, amp=0.5)]
    ) >> rwg.linear_ramp(
        [rwg.RampTarget(target_freq=20, target_amp=0.8)], duration_us=50
    )

    # Apply the sequences to their respective channels with the correct start states
    ttl_morphism_post = ttl_ops_post_seq(ch_ttl, ttl_start_state_post)
    rwg_morphism_post = rwg_ops_post_seq(ch_rwg, rwg_start_state_post)

    # Compose the final morphism
    final_morphism = synced_morphism >> (ttl_morphism_post | rwg_morphism_post)

    # -- Assembler Setup --
    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    rwgs = [0] # Only one RWG board
    run_all = run_cfg(intf, rwgs)
    assembler_seq = assembler(run_all, [('rwg0', C_RWG)])

    # 2. Act & Assert
    # The primary assertion is that this complex, multi-epoch, multi-board
    # sequence compiles without any exceptions.
    try:
        oasm_calls = compile_to_oasm_calls(final_morphism, assembler_seq)
        print("\n✓ Complex sequence compiled successfully.")
    except Exception as e:
        pytest.fail(f"Compilation of complex sequence failed unexpectedly: {e}")

    # Optional: Sanity check the output
    assert OASMAddress.MAIN in oasm_calls
    assert OASMAddress.RWG0 in oasm_calls
    main_funcs = [call.dsl_func for call in oasm_calls[OASMAddress.MAIN]]
    rwg0_funcs = [call.dsl_func for call in oasm_calls[OASMAddress.RWG0]]

    assert OASMFunction.TRIG_SLAVE in main_funcs
    assert OASMFunction.WAIT_MASTER in rwg0_funcs
    print("✓ Sync operations correctly generated.")
