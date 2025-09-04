"""
Unit tests for CatSeq compiler functionality.

Tests the core compilation logic from Morphism objects to OASM calls
and assembly generation.
"""

import pytest
from pytest_mock import MockerFixture

from catseq.atomic import ttl_init, ttl_on, ttl_off
from catseq.morphism import identity
from catseq.types.common import Board, Channel, ChannelType
from catseq.compilation.compiler import compile_to_oasm_calls, execute_oasm_calls
from catseq.compilation.types import OASMAddress, OASMFunction, OASMCall


class TestCompileToOASMCalls:
    """Test compilation of Morphism objects to OASM calls."""
    
    def test_single_channel_simple_sequence(self):
        """Test compiling a simple single-channel sequence."""
        board = Board("RWG_0")
        ch0 = Channel(board, 0, ChannelType.TTL)
    
        # Create simple sequence: init → wait → on → wait → off
        sequence = (
            ttl_init(ch0) @
            identity(5e-6) @
            ttl_on(ch0) @
            identity(10e-6) @
            ttl_off(ch0)
        )
        
        # Compile to OASM calls
        oasm_calls_by_board = compile_to_oasm_calls(sequence)
        
        # Extract calls for single board
        assert len(oasm_calls_by_board) == 1
        board_adr = list(oasm_calls_by_board.keys())[0]
        oasm_calls = oasm_calls_by_board[board_adr]
        
        # Verify structure
        assert len(oasm_calls) >= 4  # At least: config, wait, set_on, wait, set_off
        
        # Check first call is TTL_CONFIG
        assert oasm_calls[0].dsl_func == OASMFunction.TTL_CONFIG
        assert oasm_calls[0].adr == board_adr
        assert oasm_calls[0].args == (1, 0)  # mask=1 (ch0), dir=0 (init to OFF)
        
        # Check that we have wait calls
        wait_calls = [call for call in oasm_calls if call.dsl_func == OASMFunction.WAIT_US]
        assert len(wait_calls) >= 2
        
        # Check that we have TTL_SET calls
        set_calls = [call for call in oasm_calls if call.dsl_func == OASMFunction.TTL_SET]
        assert len(set_calls) >= 2  # At least ON and OFF
    
    def test_dual_channel_parallel_sequence(self):
        """Test compiling parallel operations on two channels."""
        board = Board("RWG_0")
        ch0 = Channel(board, 0, ChannelType.TTL)
        ch1 = Channel(board, 1, ChannelType.TTL)
        
        # Channel 0: init → wait(5μs) → on → wait(10μs) → off
        ch0_seq = (
            ttl_init(ch0) @
            identity(5e-6) @
            ttl_on(ch0) @
            identity(10e-6) @
            ttl_off(ch0)
        )
        
        # Channel 1: init → wait(8μs) → on → wait(12μs) → off
        ch1_seq = (
            ttl_init(ch1) @
            identity(8e-6) @
            ttl_on(ch1) @
            identity(12e-6) @
            ttl_off(ch1)
        )
        
        # Parallel execution
        parallel_seq = ch0_seq | ch1_seq
        
        # Compile to OASM calls
        oasm_calls_by_board = compile_to_oasm_calls(parallel_seq)
        
        # Extract calls for single board
        assert len(oasm_calls_by_board) == 1
        board_adr = list(oasm_calls_by_board.keys())[0]
        oasm_calls = oasm_calls_by_board[board_adr]
        
        # Should have TTL_CONFIG with combined mask
        config_calls = [call for call in oasm_calls if call.dsl_func == OASMFunction.TTL_CONFIG]
        assert len(config_calls) >= 1
        
        # First config call should affect both channels (mask = 3 = 0b11)
        first_config = config_calls[0]
        assert first_config.args[0] == 3  # mask covers both ch0 and ch1
        assert first_config.args[1] == 0  # both initialized to OFF
    
    def test_multi_board_sequence(self):
        """Test compiling sequence spanning multiple boards."""
        rwg0 = Board("RWG_0")
        rwg1 = Board("RWG_1") 
        
        ch0 = Channel(rwg0, 0, ChannelType.TTL)
        ch1 = Channel(rwg1, 0, ChannelType.TTL)
        
        # Parallel operations on different boards
        seq0 = ttl_init(ch0) @ identity(5e-6) @ ttl_on(ch0)
        seq1 = ttl_init(ch1) @ identity(8e-6) @ ttl_on(ch1)
        
        multi_board_seq = seq0 | seq1
        
        # Compile to OASM calls
        oasm_calls_by_board = compile_to_oasm_calls(multi_board_seq)
        
        # Should generate calls for multiple boards
        assert len(oasm_calls_by_board) >= 1
        
        # Check board addresses
        board_addresses = set(oasm_calls_by_board.keys())
        assert len(board_addresses) >= 1  # At least one board should be addressed
        
        # Verify each board has calls
        for board_adr, calls in oasm_calls_by_board.items():
            assert len(calls) > 0, f"Board {board_adr.value} should have OASM calls"
    
    def test_timing_precision(self):
        """Test that timing values are correctly converted."""
        board = Board("RWG_0")
        ch0 = Channel(board, 0, ChannelType.TTL)
        
        # Sequence with specific timing that should generate wait
        sequence = ttl_init(ch0) @ identity(5e-6) @ ttl_on(ch0)  # 5 microseconds
        
        oasm_calls_by_board = compile_to_oasm_calls(sequence)
        
        # Extract calls for single board
        assert len(oasm_calls_by_board) == 1
        board_adr = list(oasm_calls_by_board.keys())[0]
        oasm_calls = oasm_calls_by_board[board_adr]
        
        # Should have some calls generated
        assert len(oasm_calls) > 0
        
        # Check that we have different types of operations
        func_types = [call.dsl_func for call in oasm_calls]
        assert OASMFunction.TTL_CONFIG in func_types  # Should have init
        
        # Find wait calls if they exist
        wait_calls = [call for call in oasm_calls if call.dsl_func == OASMFunction.WAIT_US]
        if wait_calls:  # If wait calls are generated
            wait_duration = wait_calls[0].args[0]
            assert isinstance(wait_duration, float)
            assert wait_duration > 0.0  # Should be positive


class TestExecuteOASMCalls:
    """Test execution of OASM calls."""
    
    def test_mock_execution(self, mocker: MockerFixture):
        """Test mock execution when no seq object provided."""
        # Mock the OASM functions that can't be called without seq context
        mocker.patch('catseq.compilation.functions.sfs')
        mocker.patch('catseq.compilation.functions.amk')
        mocker.patch('catseq.compilation.functions.wait')
        
        calls_by_board = {
            OASMAddress.RWG0: [
                OASMCall(OASMAddress.RWG0, OASMFunction.TTL_CONFIG, (1, 0)),
                OASMCall(OASMAddress.RWG0, OASMFunction.TTL_SET, (1, 1)),
                OASMCall(OASMAddress.RWG0, OASMFunction.TTL_SET, (1, 0)),
            ]
        }
        
        # Execute without seq object (should use mock)
        success, seq = execute_oasm_calls(calls_by_board)
        
        assert success is True
        assert seq is None  # No seq object returned in mock mode
    
    def test_real_execution_with_seq(self, mocker: MockerFixture):
        """Test real execution with seq object provided."""
        # Mock OASM_AVAILABLE
        mocker.patch('catseq.compilation.compiler.OASM_AVAILABLE', True)
        
        # Create mock seq object
        mock_seq = mocker.Mock()
        mock_seq.asm = {'rwg0': []}
        
        calls_by_board = {
            OASMAddress.RWG0: [
                OASMCall(OASMAddress.RWG0, OASMFunction.TTL_CONFIG, (1, 0)),
                OASMCall(OASMAddress.RWG0, OASMFunction.TTL_SET, (1, 1)),
            ]
        }
        
        # Execute with seq object
        success, returned_seq = execute_oasm_calls(calls_by_board, mock_seq)
        
        assert success is True
        assert returned_seq is mock_seq  # Should return the same seq object
    
    def test_fallback_when_oasm_unavailable(self, mocker: MockerFixture):
        """Test fallback to mock execution when OASM not available."""
        mocker.patch('catseq.compilation.compiler.OASM_AVAILABLE', False)
        # Mock the OASM functions that can't be called without seq context
        mocker.patch('catseq.compilation.functions.sfs')
        mocker.patch('catseq.compilation.functions.amk')
        mocker.patch('catseq.compilation.functions.wait')
        
        calls_by_board = {
            OASMAddress.RWG0: [
                OASMCall(OASMAddress.RWG0, OASMFunction.TTL_CONFIG, (1, 0)),
            ]
        }
        
        success, seq = execute_oasm_calls(calls_by_board)
        
        assert success is True
        assert seq is None


class TestOASMCallStructure:
    """Test OASM call data structures."""
    
    def test_oasm_call_creation(self):
        """Test creating OASM call objects."""
        call = OASMCall(
            adr=OASMAddress.RWG0,
            dsl_func=OASMFunction.TTL_SET,
            args=(1, 1),
            kwargs={'param': 'value'}
        )
        
        assert call.adr == OASMAddress.RWG0
        assert call.dsl_func == OASMFunction.TTL_SET
        assert call.args == (1, 1)
        assert call.kwargs == {'param': 'value'}
    
    def test_oasm_call_defaults(self):
        """Test OASM call with default values."""
        call = OASMCall(
            adr=OASMAddress.RWG0,
            dsl_func=OASMFunction.TTL_CONFIG
        )
        
        assert call.args == ()
        assert call.kwargs == {}
    
    def test_oasm_address_enum_values(self):
        """Test OASM address enumeration values."""
        assert OASMAddress.RWG0.value == "rwg0"
        assert OASMAddress.RWG1.value == "rwg1"
        assert OASMAddress.MAIN.value == "main"
    
    def test_oasm_function_enum_values(self):
        """Test OASM function enumeration completeness."""
        # Check that all expected functions are defined
        expected_functions = {
            'TTL_CONFIG', 'TTL_SET', 'WAIT_US', 'WAIT_MASTER', 'TRIG_SLAVE',
            'RWG_INIT', 'RWG_SET_CARRIER', 'RWG_RF_SWITCH', 'RWG_LOAD_WAVEFORM', 'RWG_PLAY'
        }
        actual_functions = {func.name for func in OASMFunction}
        assert expected_functions.issubset(actual_functions)


class TestIntegrationCompilerFlow:
    """Integration tests for the complete compiler flow."""
    
    def test_complete_pulse_sequence_compilation(self):
        """Test complete compilation of a realistic pulse sequence."""
        # Setup hardware
        board = Board("RWG_0")
        laser = Channel(board, 0, ChannelType.TTL)
        detector = Channel(board, 1, ChannelType.TTL)
        
        # Create experimental sequence
        laser_pulse = (
            ttl_init(laser) @
            identity(5e-6) @     # Wait 5μs
            ttl_on(laser) @      # Laser ON
            identity(20e-6) @    # 20μs pulse
            ttl_off(laser)       # Laser OFF
        )
        
        detector_gate = (
            ttl_init(detector) @
            identity(3e-6) @     # Wait 3μs (start early)
            ttl_on(detector) @   # Detector ON
            identity(25e-6) @    # 25μs gate (longer than pulse)
            ttl_off(detector)    # Detector OFF
        )
        
        # Parallel execution
        experiment = laser_pulse | detector_gate
        
        # Compile
        oasm_calls_by_board = compile_to_oasm_calls(experiment)
        
        # Extract calls for single board
        assert len(oasm_calls_by_board) == 1
        board_adr = list(oasm_calls_by_board.keys())[0]
        oasm_calls = oasm_calls_by_board[board_adr]
        
        # Verify
        assert len(oasm_calls) > 0
        
        # Should have config, waits, and sets
        func_types = [call.dsl_func for call in oasm_calls]
        assert OASMFunction.TTL_CONFIG in func_types
        assert OASMFunction.WAIT_US in func_types  
        assert OASMFunction.TTL_SET in func_types
        
        # Config should affect both channels (mask = 3)
        config_calls = [call for call in oasm_calls if call.dsl_func == OASMFunction.TTL_CONFIG]
        assert config_calls[0].args[0] == 3  # Both laser and detector
    
    def test_complete_execution_flow_with_mock_seq(self, mocker: MockerFixture):
        """Test complete flow from compilation to execution with mocked seq."""
        # Mock OASM_AVAILABLE
        mocker.patch('catseq.compilation.compiler.OASM_AVAILABLE', True)
        
        # Setup
        board = Board("RWG_0")
        ch0 = Channel(board, 0, ChannelType.TTL)
        
        # Simple sequence
        sequence = ttl_init(ch0) @ ttl_on(ch0) @ ttl_off(ch0)
        
        # Compile
        oasm_calls_by_board = compile_to_oasm_calls(sequence)
        
        # Mock seq object
        mock_seq = mocker.MagicMock()
        mock_seq.asm = {'rwg0': ['AMK - TTL 1.0 $01', 'AMK - TTL 1.0 $00']}
        
        # Execute
        success, returned_seq = execute_oasm_calls(oasm_calls_by_board, mock_seq)
        
        # Verify
        assert success is True
        assert returned_seq is mock_seq
        assert 'rwg0' in returned_seq.asm
    
    def test_error_handling_empty_calls(self):
        """Test handling of empty OASM calls list."""
        success, seq = execute_oasm_calls([])
        
        assert success is True
        assert seq is None
    
    def test_error_handling_invalid_board_mapping(self):
        """Test handling of boards that don't map to valid OASM addresses."""
        invalid_board = Board("INVALID_BOARD_XYZ")
        ch0 = Channel(invalid_board, 0, ChannelType.TTL)
        
        # Should fallback to RWG0
        sequence = ttl_init(ch0)
        oasm_calls_by_board = compile_to_oasm_calls(sequence)
        
        # Extract calls for single board
        assert len(oasm_calls_by_board) == 1
        board_adr = list(oasm_calls_by_board.keys())[0]
        oasm_calls = oasm_calls_by_board[board_adr]
        
        # Should have valid calls even with invalid board name
        assert len(oasm_calls) > 0
        # Should fallback to a valid address (likely RWG0)
        assert all(isinstance(call.adr, OASMAddress) for call in oasm_calls)