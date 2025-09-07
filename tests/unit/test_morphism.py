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
    State,
)
from catseq.types.ttl import TTLState
from catseq.types.rwg import RWGActive, StaticWaveform
from catseq.hardware import ttl, rwg
from catseq.morphism import identity

# Define boards and channels for testing
RWG0 = Board("RWG0")
CH0 = Channel(RWG0, 0, ChannelType.TTL)
CH1 = Channel(RWG0, 1, ChannelType.TTL)
RWG_CH0 = Channel(RWG0, 0, ChannelType.RWG)

def test_sequential_composition_with_identity():
    """
    Tests that the >> operator correctly appends an identity (wait)
    operation to all lanes of a morphism.
    """
    # Arrange
    m1 = ttl.on()(CH0, start_state=TTLState.OFF)
    id_morphism = identity(10)  # 10us wait

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
    assert last_op.start_state == TTLState.ON  # State is correctly inferred
    assert last_op.end_state == TTLState.ON

def test_parallel_composition_pads_shorter_morphism():
    """
    Tests that the | operator correctly pads the shorter morphism with
    an identity operation to match the length of the longer one.
    """
    # Arrange
    m_short = ttl.on()(CH0, start_state=TTLState.OFF)
    m_long = ttl.on()(CH1, start_state=TTLState.OFF) >> identity(20)

    # Act
    m_parallel = m_short | m_long

    # Assert
    # 1. Check that durations are now equal
    assert (
        m_parallel.lanes[CH0].total_duration_cycles
        == m_parallel.lanes[CH1].total_duration_cycles
    )
    assert m_parallel.total_duration_cycles == m_long.total_duration_cycles

    # 2. Check that the shorter lane was padded
    ch0_lane = m_parallel.lanes[CH0]
    assert len(ch0_lane.operations) == 2
    padding_op = ch0_lane.operations[1]
    assert padding_op.operation_type == OperationType.IDENTITY
    assert padding_op.start_state == TTLState.ON  # State inherited from ttl_on

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
        return (
            ttl.on()(channel, start_state=TTLState.OFF)
            >> identity(duration_us)
            >> ttl.off()(channel, start_state=TTLState.ON)
        )

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
    mock_op2.operation_type = OperationType.TTL_ON  # Type doesn't matter
    mock_op2.start_state = TTLState.OFF
    mock_op2.duration_cycles = 1
    lane2 = Lane(operations=(mock_op2,))
    m2 = Morphism(lanes={CH0: lane2})

    # Act & Assert
    with pytest.raises(ValueError, match="State mismatch for channel"):
        _ = m1 @ m2

def test_morphism_sequence_state_propagation():
    """
    Tests that state is correctly propagated through a chained sequence
    of MorphismDefs (op1 >> op2 >> op3). This specifically tests the
    state inference logic within MorphismSequence.
    """
    # 1. Arrange
    # Define a sequence of operations that will clearly show state changes.
    # The sequence is OFF -> ON -> OFF -> ON.
    op1 = ttl.on()
    op2 = ttl.off()
    op3 = ttl.on()
    sequence = op1 >> op2 >> op3

    # 2. Act
    # Apply the sequence to a channel starting in the OFF state.
    morphism = sequence(CH0, start_state=TTLState.OFF)

    # 3. Assert
    # Check the lane to ensure each atomic operation has the correct
    # start and end states, proving that the state was propagated correctly
    # from one step to the next.
    ops = morphism.lanes[CH0].operations

    # There should be 3 operations in the sequence.
    assert len(ops) == 3, "The final morphism should contain 3 operations."

    # Check op1: ttl_on()
    # Should transition from the initial state OFF to ON.
    assert ops[0].operation_type == OperationType.TTL_ON
    assert ops[0].start_state == TTLState.OFF, "Op1 should start OFF"
    assert ops[0].end_state == TTLState.ON, "Op1 should end ON"

    # Check op2: ttl_off()
    # Should transition from op1's end state (ON) to OFF.
    assert ops[1].operation_type == OperationType.TTL_OFF
    assert ops[1].start_state == TTLState.ON, "Op2 should start ON"
    assert ops[1].end_state == TTLState.OFF, "Op2 should end OFF"

    # Check op3: ttl_on()
    # Should transition from op2's end state (OFF) to ON.
    assert ops[2].operation_type == OperationType.TTL_ON
    assert ops[2].start_state == TTLState.OFF, "Op3 should start OFF"
    assert ops[2].end_state == TTLState.ON, "Op3 should end ON"


def test_rwg_rf_pulse_composite_operation():
    """
    Tests that rf_pulse creates the correct composite operation:
    rf_on → wait → rf_off, with proper state transitions.
    """
    # Arrange
    waveforms = (StaticWaveform(sbg_id=0, freq=10.0, amp=0.5, phase=0.0),)
    start_state = RWGActive(
        carrier_freq=1000.0,
        rf_on=False,  # Must start with RF off
        waveforms=waveforms
    )
    
    pulse_duration_us = 50.0
    rf_pulse_def = rwg.rf_pulse(pulse_duration_us)
    
    # Act
    morphism = rf_pulse_def(RWG_CH0, start_state)
    
    # Assert
    # 1. Check that we have exactly one lane for our channel
    assert len(morphism.lanes) == 1
    assert RWG_CH0 in morphism.lanes
    
    # 2. Check that the composite operation has 3 atomic operations
    ops = morphism.lanes[RWG_CH0].operations
    assert len(ops) == 3, "RF pulse should contain exactly 3 operations"
    
    # 3. Check operation sequence and states
    # Operation 1: RF ON
    assert ops[0].operation_type == OperationType.RWG_RF_SWITCH
    assert ops[0].start_state.rf_on == False, "RF should start OFF"
    assert ops[0].end_state.rf_on == True, "RF should be ON after first op"
    
    # Operation 2: IDENTITY (wait)
    assert ops[1].operation_type == OperationType.IDENTITY
    # Check that wait duration matches user specification (converted to cycles)
    expected_wait_cycles = int(pulse_duration_us * 250)  # 250 MHz clock
    assert ops[1].duration_cycles == expected_wait_cycles
    
    # Operation 3: RF OFF
    assert ops[2].operation_type == OperationType.RWG_RF_SWITCH
    assert ops[2].start_state.rf_on == True, "RF should start ON for OFF operation"
    assert ops[2].end_state.rf_on == False, "RF should be OFF after final op"
    
    # 4. Check domain and codomain (external view)
    first_op_start = ops[0].start_state
    last_op_end = ops[2].end_state
    assert first_op_start.rf_on == False, "Domain should have rf_on=False"
    assert last_op_end.rf_on == False, "Codomain should have rf_on=False"
    
    # 5. Verify that waveforms and carrier_freq are preserved
    assert first_op_start.carrier_freq == last_op_end.carrier_freq
    assert first_op_start.waveforms == last_op_end.waveforms


def test_rwg_rf_pulse_invalid_start_state():
    """
    Tests that rf_pulse raises appropriate errors for invalid start states.
    """
    # Test 1: Non-RWGActive state
    with pytest.raises(TypeError, match="RF pulse requires RWGActive state"):
        pulse_def = rwg.rf_pulse(50.0)
        pulse_def(RWG_CH0, TTLState.OFF)  # Wrong state type
    
    # Test 2: RWGActive but with rf_on=True
    waveforms = (StaticWaveform(sbg_id=0, freq=10.0, amp=0.5, phase=0.0),)
    invalid_state = RWGActive(
        carrier_freq=1000.0,
        rf_on=True,  # Invalid: RF already on
        waveforms=waveforms
    )
    
    with pytest.raises(ValueError, match="RF pulse requires rf_on=False"):
        pulse_def = rwg.rf_pulse(50.0)
        pulse_def(RWG_CH0, invalid_state)