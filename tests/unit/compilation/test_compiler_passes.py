"""
Unit tests for the CatSeq compiler passes.
"""
import pytest
from catseq.compilation.compiler import (
    _pass0_extract_events,
    _pass1_translate_to_oasm,
    _pass2_analyze_costs,
    _estimate_oasm_cost,
    OASM_FUNCTION_MAP
)
from catseq.compilation.types import OASMAddress, OASMFunction, OASMCall
from catseq.compilation.functions import rwg_load_waveform
from catseq.types.common import OperationType, AtomicMorphism
from catseq.types.rwg import WaveformParams
from catseq.morphism import Morphism, identity
from catseq.lanes import Lane
from catseq.atomic import rwg_load_coeffs
from catseq.types.common import Board, Channel, ChannelType, OperationType
from catseq.types.rwg import RWGReady

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
    board = Board("RWG_0")
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

    # 2. Calculate the Expected Cost (Golden Standard)
    # Directly call the OASM DSL function to see what assembly it produces.
    intf = sim_intf()
    run_config = run_cfg(intf, [1], core=C_RWG)
    temp_seq = assembler(run_config, [('rwg0', C_RWG)])
    
    # This is a bit of a hack: the oasm functions are singletons. We need to
    # manually call the sequencer with the function and its captured state.
    # In a real scenario, the sequencer would handle this.
    # NOTE: This part of the test is fragile and depends on oasm implementation details.
    # A better approach would be a more direct way to get assembly from a function call.
    # For now, we assume the user-provided function populates the assembler state correctly.
    
    # Let's manually create the call and execute it to be safe.
    temp_seq_for_golden = assembler(run_config, [('rwg0', C_RWG)])
    temp_seq_for_golden('rwg0', rwg_load_waveform, test_waveform_params)

    # assert 'rwg0' in temp_seq_for_golden.asm, "Golden standard assembly generation failed"
    golden_binary_asm = temp_seq_for_golden.asm['rwg0']
    golden_asm_lines = disassembler(core=C_RWG)(golden_binary_asm)
    print(golden_asm_lines)
    
    expected_cost = _estimate_oasm_cost(golden_asm_lines)
    assert expected_cost > 0, "Golden standard cost should be greater than zero"

    # 3. Run the Compiler Passes
    # Pass 0: Extract Events
    events_by_board = _pass0_extract_events(morphism)
    
    # Pass 1: Translate to OASM
    _pass1_translate_to_oasm(events_by_board)

    # Pass 2: Analyze Costs
    _pass2_analyze_costs(events_by_board)

    # 4. Find the relevant event and Assert
    rwg0_events = events_by_board[OASMAddress.RWG0]
    load_event = None
    for event in rwg0_events:
        if event.operation.operation_type == OperationType.RWG_LOAD_COEFFS:
            load_event = event
            break
    
    assert load_event is not None, "Could not find the RWG_LOAD_COEFFS event"
    
    # The core assertion of the test
    assert load_event.cost_cycles == expected_cost, \
        f"Compiler calculated cost ({load_event.cost_cycles}) does not match expected cost ({expected_cost})"

    print(f"\n✅ Test successful: RWG_LOAD_COEFFS cost correctly calculated as {expected_cost} cycles.")
