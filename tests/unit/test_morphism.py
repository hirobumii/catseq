import pytest
from catseq.morphism import Morphism
from catseq.lanes import Lane
from catseq.time_utils import us_to_cycles
from catseq.types.common import (
    AtomicMorphism,
    Board,
    Channel,
    ChannelType,
    OperationType,
)
from catseq.types.ttl import TTLState
from catseq.atomic import ttl_on, ttl_off
from catseq.morphism import identity

# Define boards and channels for testing
RWG0 = Board("RWG0")
CH0 = Channel(RWG0, 0, ChannelType.TTL)
CH1 = Channel(RWG0, 1, ChannelType.TTL)

def test_sequential_composition_with_identity():
    """
    Tests that the >> operator correctly appends an identity (wait)
    operation to all lanes of a morphism.
    """
    # Arrange
    m1 = ttl_on(CH0)
    id_morphism = identity(10) # 10us wait

    # Act
    m2 = m1 >> id_morphism

    # Assert
    # 1. Check total duration
    original_duration = m1.total_duration_cycles
    identity_duration = id_morphism.total_duration_cycles
    assert m2.total_duration_cycles == original_duration + identity_duration

    # 2. Check the lane content
    assert len(m2.lanes[CH0].operations) == 2
    last_op = m2.lanes[CH0].operations[1]
    assert last_op.operation_type == OperationType.IDENTITY
    assert last_op.duration_cycles == identity_duration
    assert last_op.start_state == TTLState.ON # State is correctly inferred
    assert last_op.end_state == TTLState.ON

def test_parallel_composition_pads_shorter_morphism():
    """
    Tests that the | operator correctly pads the shorter morphism with
    an identity operation to match the length of the longer one.
    """
    # Arrange
    m_short = ttl_on(CH0) # duration is very short
    m_long = ttl_on(CH1) >> identity(20) # duration is much longer

    # Act
    m_parallel = m_short | m_long

    # Assert
    # 1. Check that durations are now equal
    assert m_parallel.lanes[CH0].total_duration_cycles == m_parallel.lanes[CH1].total_duration_cycles
    assert m_parallel.total_duration_cycles == m_long.total_duration_cycles

    # 2. Check that the shorter lane was padded
    ch0_lane = m_parallel.lanes[CH0]
    assert len(ch0_lane.operations) == 2
    padding_op = ch0_lane.operations[1]
    assert padding_op.operation_type == OperationType.IDENTITY
    assert padding_op.start_state == TTLState.ON # State inherited from ttl_on

def test_complex_composition_scenario_as_specified_by_user():
    """
    Tests a complex user-defined scenario:
    (pulse(CH0, 10) | pulse(CH1, 15)) >> identity(10) @ (pulse(CH0, 15) | pulse(CH1, 15))
    This validates the interplay of parallel alignment, sequential broadcast,
    and strict composition.
    """
    # Arrange
    # A local helper function for creating a clear pulse definition for this test
    def pulse(channel: Channel, duration_us: float) -> Morphism:
        """A simple pulse defined as ON -> identity(duration) -> OFF."""
        return ttl_on(channel) >> identity(duration_us) >> ttl_off(channel)

    # Part 1: Parallel pulses of different lengths.
    # The '|' operator will align them by padding the shorter pulse (CH0).
    m1 = pulse(CH0, 10) | pulse(CH1, 15)

    # Part 2: A global wait, applied to all channels via '>>'
    m2_wait = identity(10)

    # Part 3: Another block of parallel pulses.
    # The '@' operator will check if their start states match the end states
    # of the previous block.
    m3 = pulse(CH0, 15) | pulse(CH1, 15)

    # Act
    m_final = (m1 >> m2_wait) @ m3

    # Assert
    # 1. Check total duration.
    # Duration of m1 is determined by the longest element, pulse(CH1, 15).
    duration_m1 = pulse(CH1, 15).total_duration_cycles
    duration_m2 = m2_wait.total_duration_cycles
    # Duration of m3 is pulse(CH0, 15) as both are equal.
    duration_m3 = pulse(CH0, 15).total_duration_cycles
    expected_total_cycles = duration_m1 + duration_m2 + duration_m3
    assert m_final.total_duration_cycles == expected_total_cycles

    # 2. Verify the number of atomic operations in each lane.
    # This confirms that padding and concatenation happened correctly.
    # CH0 lane: [on, id(10), off, pad(5)] >> id(10) @ [on, id(15), off]
    # Expected ops: 4 + 1 + 3 = 8
    assert len(m_final.lanes[CH0].operations) == 8
    
    # CH1 lane: [on, id(15), off] >> id(10) @ [on, id(15), off]
    # Expected ops: 3 + 1 + 3 = 7
    assert len(m_final.lanes[CH1].operations) == 7

def test_strict_composition_raises_error_on_state_mismatch(mocker):
    """
    Tests that the @ operator raises a ValueError when the end state of the
    first morphism does not match the start state of the second one.
    Uses pytest-mock to isolate the composition logic.
    """
    # Arrange
    # We use real dataclasses for Morphism and Lane, but mock the
    # AtomicMorphism inside to control the states precisely.

    # Morphism 1, ending in state ON
    mock_op1 = mocker.Mock(spec=AtomicMorphism)
    mock_op1.operation_type = OperationType.TTL_ON
    mock_op1.end_state = TTLState.ON
    mock_op1.duration_cycles = 1
    # The __post_init__ of Morphism requires lanes to have equal duration.
    # We create a Lane with a mocked operation, so we must patch the
    # lane's duration to return a consistent value.
    lane1 = Lane(operations=(mock_op1,))
    m1 = Morphism(lanes={CH0: lane1})

    # Morphism 2, starting in state OFF (which is a mismatch)
    mock_op2 = mocker.Mock(spec=AtomicMorphism)
    mock_op2.operation_type = OperationType.TTL_ON # Type doesn't matter
    mock_op2.start_state = TTLState.OFF
    mock_op2.duration_cycles = 1
    lane2 = Lane(operations=(mock_op2,))
    m2 = Morphism(lanes={CH0: lane2})

    # Act & Assert
    with pytest.raises(ValueError, match="State mismatch for channel"):
        _ = m1 @ m2
