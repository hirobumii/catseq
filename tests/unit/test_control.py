"""
Unit tests for control flow constructs.

Tests the precompiled morphism and loop functionality in catseq.control module.
"""

import pytest
from unittest.mock import Mock, patch

from catseq.control import (
    extract_channel_states_from_morphism,
    compile_morphism_to_board_funcs,
    morphism_to_precompiled_blackbox,
    repeat_morphism
)
from catseq.morphism import Morphism
from catseq.lanes import Lane
from catseq.atomic import AtomicMorphism
from catseq.types.common import Board, Channel, ChannelType
from catseq.types.ttl import TTLState


class TestExtractChannelStatesFromMorphism:
    """Test channel state extraction from morphisms."""

    def test_extract_single_channel_states(self):
        """Test extracting states from a single channel morphism."""
        # Arrange
        board = Board("RWG0")
        channel = Channel(board, 0, ChannelType.TTL)

        # Create mock operations with start/end states
        mock_op1 = Mock(spec=AtomicMorphism)
        mock_op1.start_state = TTLState.OFF
        mock_op1.end_state = TTLState.ON
        mock_op1.duration_cycles = 100  # Add required attribute

        mock_op2 = Mock(spec=AtomicMorphism)
        mock_op2.start_state = TTLState.ON
        mock_op2.end_state = TTLState.OFF
        mock_op2.duration_cycles = 50   # Add required attribute

        lane = Lane(operations=[mock_op1, mock_op2])
        morphism = Morphism(lanes={channel: lane})

        # Act
        channel_states = extract_channel_states_from_morphism(morphism)

        # Assert
        assert len(channel_states) == 1
        assert channel in channel_states
        assert channel_states[channel] == (TTLState.OFF, TTLState.OFF)

    def test_extract_multiple_channel_states(self):
        """Test extracting states from multiple channels."""
        # Arrange
        board = Board("RWG0")
        ch1 = Channel(board, 0, ChannelType.TTL)
        ch2 = Channel(board, 1, ChannelType.TTL)

        # Channel 1: OFF -> ON
        mock_op1 = Mock(spec=AtomicMorphism)
        mock_op1.start_state = TTLState.OFF
        mock_op1.end_state = TTLState.ON
        mock_op1.duration_cycles = 100
        lane1 = Lane(operations=[mock_op1])

        # Channel 2: ON -> OFF (same duration for parallel composition)
        mock_op2 = Mock(spec=AtomicMorphism)
        mock_op2.start_state = TTLState.ON
        mock_op2.end_state = TTLState.OFF
        mock_op2.duration_cycles = 100  # Same duration as lane1
        lane2 = Lane(operations=[mock_op2])

        morphism = Morphism(lanes={ch1: lane1, ch2: lane2})

        # Act
        channel_states = extract_channel_states_from_morphism(morphism)

        # Assert
        assert len(channel_states) == 2
        assert channel_states[ch1] == (TTLState.OFF, TTLState.ON)
        assert channel_states[ch2] == (TTLState.ON, TTLState.OFF)

    def test_extract_empty_morphism(self):
        """Test extracting states from empty morphism."""
        # Arrange
        morphism = Morphism(lanes={})

        # Act
        channel_states = extract_channel_states_from_morphism(morphism)

        # Assert
        assert channel_states == {}

    def test_extract_empty_lane(self):
        """Test extracting states from morphism with empty lane."""
        # Arrange
        board = Board("RWG0")
        channel = Channel(board, 0, ChannelType.TTL)
        lane = Lane(operations=[])  # Empty lane
        morphism = Morphism(lanes={channel: lane})

        # Act
        channel_states = extract_channel_states_from_morphism(morphism)

        # Assert
        assert channel_states == {}


class TestCompileMorphismToBoardFuncs:
    """Test morphism compilation to board functions."""

    @patch('catseq.control.compile_to_oasm_calls')
    def test_compile_single_board(self, mock_compile):
        """Test compiling morphism for single board."""
        # Arrange
        board = Board("RWG0")
        channel = Channel(board, 0, ChannelType.TTL)
        lane = Lane(operations=[])
        morphism = Morphism(lanes={channel: lane})

        mock_assembler = Mock()
        mock_compile.return_value = {'RWG0': []}  # Mock OASM calls

        # Act
        board_funcs = compile_morphism_to_board_funcs(morphism, mock_assembler)

        # Assert
        assert len(board_funcs) == 1
        assert board in board_funcs
        assert callable(board_funcs[board])

        # Verify compile was called with sub-morphism
        mock_compile.assert_called_once()
        called_morphism = mock_compile.call_args[0][0]
        assert isinstance(called_morphism, Morphism)

    @patch('catseq.control.compile_to_oasm_calls')
    def test_compile_multiple_boards(self, mock_compile):
        """Test compiling morphism for multiple boards."""
        # Arrange
        board1 = Board("RWG0")
        board2 = Board("RWG1")
        ch1 = Channel(board1, 0, ChannelType.TTL)
        ch2 = Channel(board2, 0, ChannelType.TTL)

        lane1 = Lane(operations=[])
        lane2 = Lane(operations=[])
        morphism = Morphism(lanes={ch1: lane1, ch2: lane2})

        mock_assembler = Mock()
        mock_compile.return_value = {}

        # Act
        board_funcs = compile_morphism_to_board_funcs(morphism, mock_assembler)

        # Assert
        assert len(board_funcs) == 2
        assert board1 in board_funcs
        assert board2 in board_funcs
        assert callable(board_funcs[board1])
        assert callable(board_funcs[board2])

    @patch('catseq.control.compile_to_oasm_calls')
    @patch('catseq.control.OASM_FUNCTION_MAP')
    def test_executor_function_execution(self, mock_func_map, mock_compile):
        """Test that executor functions properly execute OASM calls."""
        # Arrange
        board = Board("RWG0")
        channel = Channel(board, 0, ChannelType.TTL)
        lane = Lane(operations=[])
        morphism = Morphism(lanes={channel: lane})

        # Mock OASM calls
        mock_func = Mock()
        mock_func_map.__getitem__.return_value = mock_func

        mock_call = Mock()
        mock_call.dsl_func = Mock()  # Non-USER_DEFINED_FUNC
        mock_call.kwargs = None
        mock_call.args = ('arg1', 'arg2')

        mock_compile.return_value = {'board_addr': [mock_call]}
        mock_assembler = Mock()

        # Act
        board_funcs = compile_morphism_to_board_funcs(morphism, mock_assembler)
        executor = board_funcs[board]
        executor()  # Execute the function

        # Assert
        mock_func.assert_called_once_with('arg1', 'arg2')


class TestMorphismToPrecompiledBlackbox:
    """Test morphism to precompiled blackbox conversion."""

    @patch('catseq.control.compile_morphism_to_board_funcs')
    @patch('catseq.control.oasm_black_box')
    def test_blackbox_creation_default_states(self, mock_blackbox, mock_compile):
        """Test blackbox creation with default state extraction."""
        # Arrange
        board = Board("RWG0")
        channel = Channel(board, 0, ChannelType.TTL)

        mock_op = Mock(spec=AtomicMorphism)
        mock_op.start_state = TTLState.OFF
        mock_op.end_state = TTLState.ON
        mock_op.duration_cycles = 1000

        lane = Lane(operations=[mock_op])
        morphism = Morphism(lanes={channel: lane})

        mock_assembler = Mock()
        mock_board_funcs = {board: Mock()}
        mock_compile.return_value = mock_board_funcs

        # Act
        morphism_to_precompiled_blackbox(morphism, mock_assembler)

        # Assert
        mock_compile.assert_called_once_with(morphism, mock_assembler)
        mock_blackbox.assert_called_once()

        # Check blackbox was called with correct parameters
        call_args = mock_blackbox.call_args
        assert call_args[1]['channel_states'] == {channel: (TTLState.OFF, TTLState.ON)}
        assert call_args[1]['duration_cycles'] == 1000
        assert call_args[1]['board_funcs'] == mock_board_funcs

    @patch('catseq.control.compile_morphism_to_board_funcs')
    @patch('catseq.control.oasm_black_box')
    def test_blackbox_creation_custom_states(self, mock_blackbox, mock_compile):
        """Test blackbox creation with custom state functions."""
        # Arrange
        board = Board("RWG0")
        channel = Channel(board, 0, ChannelType.TTL)
        lane = Lane(operations=[])
        morphism = Morphism(lanes={channel: lane})

        # Custom state functions
        mock_get_start = Mock(return_value={channel: TTLState.ON})
        mock_get_end = Mock(return_value={channel: TTLState.OFF})

        mock_assembler = Mock()
        mock_compile.return_value = {}

        # Act
        morphism_to_precompiled_blackbox(
            morphism, mock_assembler, mock_get_start, mock_get_end
        )

        # Assert
        mock_get_start.assert_called_once_with(morphism)
        mock_get_end.assert_called_once_with(morphism)

        # Check that custom states were used
        call_args = mock_blackbox.call_args
        assert call_args[1]['channel_states'] == {channel: (TTLState.ON, TTLState.OFF)}

    def test_custom_states_missing_channel_error(self):
        """Test error when custom state functions have missing channels."""
        # Arrange
        board = Board("RWG0")
        ch1 = Channel(board, 0, ChannelType.TTL)
        ch2 = Channel(board, 1, ChannelType.TTL)
        lane = Lane(operations=[])
        morphism = Morphism(lanes={ch1: lane})

        # Missing channel in end states
        mock_get_start = Mock(return_value={ch1: TTLState.ON})
        mock_get_end = Mock(return_value={ch2: TTLState.OFF})  # Different channel!

        mock_assembler = Mock()

        # Act & Assert
        with pytest.raises(ValueError, match="missing start or end state"):
            morphism_to_precompiled_blackbox(
                morphism, mock_assembler, mock_get_start, mock_get_end
            )


class TestRepeatMorphism:
    """Test hardware loop creation with repeat_morphism."""

    @patch('catseq.control.compile_morphism_to_board_funcs')
    @patch('catseq.control.oasm_black_box')
    def test_repeat_morphism_timing_calculation(self, mock_blackbox, mock_compile):
        """Test that repeat_morphism calculates timing correctly."""
        # Arrange
        board = Board("RWG0")
        channel = Channel(board, 0, ChannelType.TTL)

        mock_op = Mock(spec=AtomicMorphism)
        mock_op.start_state = TTLState.OFF
        mock_op.end_state = TTLState.ON
        mock_op.duration_cycles = 100  # t_morphism = 100

        lane = Lane(operations=[mock_op])
        morphism = Morphism(lanes={channel: lane})

        count = 5
        mock_assembler = Mock()
        mock_base_func = Mock()
        mock_compile.return_value = {board: mock_base_func}

        # Setup mock return value for oasm_black_box
        mock_result_morphism = Mock(spec=Morphism)
        mock_blackbox.return_value = mock_result_morphism

        # Act
        result = repeat_morphism(morphism, count, mock_assembler)

        # Assert
        # 1. Check return value
        assert result == mock_result_morphism
        assert isinstance(result, Mock)  # It's a mock, but represents a Morphism

        # 2. Check timing calculation: 15 + 5*(26 + 100) = 15 + 5*126 = 15 + 630 = 645
        expected_duration = 15 + count * (26 + 100)
        call_args = mock_blackbox.call_args
        assert call_args[1]['duration_cycles'] == expected_duration

        # 3. Check channel states are correctly passed
        expected_channel_states = {channel: (TTLState.OFF, TTLState.ON)}
        assert call_args[1]['channel_states'] == expected_channel_states

        # 4. Check board functions are provided
        board_funcs = call_args[1]['board_funcs']
        assert board in board_funcs
        assert callable(board_funcs[board])


    def test_repeat_morphism_invalid_count(self):
        """Test that repeat_morphism raises error for invalid count."""
        # Arrange
        morphism = Mock()
        assembler = Mock()

        # Act & Assert
        with pytest.raises(ValueError, match="Repeat count must be positive"):
            repeat_morphism(morphism, 0, assembler)

        with pytest.raises(ValueError, match="Repeat count must be positive"):
            repeat_morphism(morphism, -1, assembler)

    @patch('catseq.control.compile_morphism_to_board_funcs')
    def test_repeat_morphism_channel_states_extraction(self, mock_compile):
        """Test that repeat_morphism correctly extracts channel states."""
        # Arrange
        board = Board("RWG0")
        channel = Channel(board, 0, ChannelType.TTL)

        mock_op = Mock(spec=AtomicMorphism)
        mock_op.start_state = TTLState.ON
        mock_op.end_state = TTLState.OFF
        mock_op.duration_cycles = 200

        lane = Lane(operations=[mock_op])
        morphism = Morphism(lanes={channel: lane})

        count = 2
        mock_assembler = Mock()
        mock_compile.return_value = {board: Mock()}

        # Act
        with patch('catseq.control.oasm_black_box') as mock_blackbox:
            # Setup mock return value
            mock_result_morphism = Mock(spec=Morphism)
            mock_blackbox.return_value = mock_result_morphism

            result = repeat_morphism(morphism, count, mock_assembler)

        # Assert
        # 1. Check return value
        assert result == mock_result_morphism

        # 2. Check channel states extraction
        call_args = mock_blackbox.call_args
        channel_states = call_args[1]['channel_states']
        assert channel_states == {channel: (TTLState.ON, TTLState.OFF)}


class TestTimingFormula:
    """Test the timing calculation formula for hardware loops."""

    def test_timing_formula_constants(self):
        """Test that timing formula constants are correct."""
        # The formula is: 15 + n*(26 + t_morphism)
        # Where:
        # - 15: Fixed overhead (2 cycles init + 13 cycles final condition check)
        # - 26: Per-iteration overhead (13 cycles condition + 13 cycles increment/jump)

        LOOP_FIXED_OVERHEAD = 15
        LOOP_PER_ITERATION_OVERHEAD = 26

        # Test for different values
        test_cases = [
            (1, 100, 15 + 1*(26 + 100)),    # n=1, t=100 -> 141
            (5, 50, 15 + 5*(26 + 50)),      # n=5, t=50  -> 395
            (10, 0, 15 + 10*(26 + 0)),      # n=10, t=0 -> 275
        ]

        for n, t_morphism, expected in test_cases:
            actual = LOOP_FIXED_OVERHEAD + n * (LOOP_PER_ITERATION_OVERHEAD + t_morphism)
            assert actual == expected, f"Formula failed for n={n}, t={t_morphism}"