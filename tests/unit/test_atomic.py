import pytest
from catseq.atomic import ttl_on
from catseq.lanes import Lane
from catseq.morphism import Morphism
from catseq.types.common import AtomicMorphism, Board, Channel, OperationType, ChannelType
from catseq.types.ttl import TTLState

# Define a board and channel for testing
RWG0 = Board("RWG0")
CH0 = Channel(RWG0, 0, ChannelType.TTL)

def test_ttl_on_creates_correct_morphism():
    """
    Tests that ttl_on() creates a valid Morphism with a single Lane
    containing a single TTL_ON operation.
    """
    # Call the function to be tested
    m = ttl_on(CH0)

    # 1. Check if the result is a Morphism instance
    assert isinstance(m, Morphism), "ttl_on should return a Morphism object"

    # 2. Check that there is exactly one lane
    assert len(m.lanes) == 1, "Morphism should contain exactly one lane"
    assert CH0 in m.lanes, "The correct channel should be in the morphism's lanes"

    # 3. Get the lane and check its properties
    lane = m.lanes[CH0]
    assert isinstance(lane, Lane), "The lane object should be of type Lane"
    # The channel is the key in the dict, not an attribute of the lane.

    # 4. Check the operations within the lane
    assert len(lane.operations) == 1, "The lane should contain exactly one operation"
    op = lane.operations[0]
    
    assert isinstance(op, AtomicMorphism), "The operation should be of type AtomicMorphism"
    assert op.operation_type == OperationType.TTL_ON, "Operation type should be TTL_ON"
    assert op.start_state == TTLState.OFF, "Start state should be OFF"
    assert op.end_state == TTLState.ON, "End state should be ON"
    assert op.duration_cycles == 1, "Duration should be 1 cycle"

def test_ttl_on_has_correct_duration():
    """
    Tests that the Morphism created by ttl_on has the correct total duration.
    """
    m = ttl_on(CH0)
    assert m.total_duration_cycles == 1, "Morphism duration should be 1 cycle"

def test_ttl_on_raises_error_for_invalid_channel():
    """
    Tests that using a morphism with an invalid channel raises an AttributeError
    when an operation requires a valid Channel object.
    """
    with pytest.raises(AttributeError):
        m = ttl_on("not_a_channel")
        # The error is deferred until an operation needs a real Channel object.
        m.lanes_by_board()