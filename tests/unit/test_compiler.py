import pytest
from catseq.compilation.compiler import compile_to_oasm_calls
from catseq.types.common import ChannelType, Board, Channel
from catseq.atomic import ttl_on, ttl_off
from catseq.morphism import identity
from catseq.morphism import Morphism

# Define boards and channels for testing
BOARD0 = Board("RWG0")
BOARD1 = Board("RWG1")
CH0 = Channel(BOARD0, 0, ChannelType.TTL)
CH1 = Channel(BOARD0, 1, ChannelType.TTL)
CH2 = Channel(BOARD1, 0, ChannelType.TTL)


def test_compile_simple_morphism():
    """Tests compilation of a simple TTL ON morphism."""
    # Arrange
    m = ttl_on(CH0)

    # Act
    oasm_calls = compile_to_oasm_calls(m)

    # Assert
    assert len(oasm_calls) > 0
    # More assertions would go here, e.g., checking call types
    # For now, just check that it runs without error and produces output
    assert oasm_calls is not None


def test_compile_sequential_morphism():
    """Tests compilation of a morphism with sequential operations."""
    # Arrange
    m = ttl_on(CH0) >> identity(10) >> ttl_off(CH0)

    # Act
    oasm_calls_by_board = compile_to_oasm_calls(m)

    # Assert
    assert len(oasm_calls_by_board) == 1
    board_adr = list(oasm_calls_by_board.keys())[0]
    oasm_calls = oasm_calls_by_board[board_adr]
    
    assert len(oasm_calls) > 1
    # Expected: TTL_SET, WAIT_US, TTL_SET
    assert "WAIT_US" in str(oasm_calls)


def test_compile_parallel_morphism():
    """Tests compilation of a morphism with parallel operations."""
    # Arrange
    m = ttl_on(CH0) | ttl_on(CH1)

    # Act
    oasm_calls_by_board = compile_to_oasm_calls(m)

    # Assert
    # Extract calls for single board
    assert len(oasm_calls_by_board) == 1
    board_adr = list(oasm_calls_by_board.keys())[0]
    oasm_calls = oasm_calls_by_board[board_adr]
    
    # Both TTLs should be set in a single OASM call if they are simultaneous
    assert len(oasm_calls) == 1
    ttl_set_call = oasm_calls[0]
    # Mask should be 3 (binary 11) for channels 0 and 1
    assert ttl_set_call.args[0] == 3


def test_compile_multi_board_morphism():
    """Tests compilation of a morphism involving multiple boards."""
    # Arrange
    m = ttl_on(CH0) | ttl_on(CH2)  # CH0 is BOARD0, CH2 is BOARD1

    # Act
    oasm_calls_by_board = compile_to_oasm_calls(m)

    # Assert
    assert len(oasm_calls_by_board) == 2
    board_addresses = {adr.value for adr in oasm_calls_by_board.keys()}
    assert "rwg0" in board_addresses
    assert "rwg1" in board_addresses