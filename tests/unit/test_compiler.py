import pytest
from catseq.compilation.compiler import compile_to_oasm_calls
from catseq.compilation.types import OASMCall, OASMFunction, OASMAddress
from catseq.types.common import Board, Channel
from catseq.atomic import ttl_on, ttl_off, identity
from catseq.time_utils import cycles_to_us, us_to_cycles

# Define a board and channel for testing
BOARD0 = Board("RWG0")
CH0 = Channel(BOARD0, 0)
CH1 = Channel(BOARD0, 1)

def test_compile_simple_pulse():
    """
    Tests compiling a simple sequence: ON -> WAIT -> OFF
    """
    # Arrange
    wait_duration_us = 10.0
    m = ttl_on(CH0) >> identity(wait_duration_us) >> ttl_off(CH0)

    # Act
    calls = compile_to_oasm_calls(m)

    # Assert
    assert len(calls) == 3

    # 1. First call should be TTL_SET to turn the channel ON
    call1 = calls[0]
    assert call1.dsl_func == OASMFunction.TTL_SET
    assert call1.adr == OASMAddress.RWG0
    assert call1.args == (1, 1) # mask=bit0, value=bit0

    # 2. Second call should be WAIT_US
    call2 = calls[1]
    assert call2.dsl_func == OASMFunction.WAIT_US
    # The wait time should be the duration of the identity op plus the duration
    # of the ttl_on op, as the wait happens between the two physical ops.
    expected_wait_cycles = ttl_on(CH0).total_duration_cycles + identity(wait_duration_us).total_duration_cycles
    expected_wait_us = cycles_to_us(expected_wait_cycles)
    assert call2.args[0] == pytest.approx(expected_wait_us)

    # 3. Third call should be TTL_SET to turn the channel OFF
    call3 = calls[2]
    assert call3.dsl_func == OASMFunction.TTL_SET
    assert call3.adr == OASMAddress.RWG0
    assert call3.args == (1, 0) # mask=bit0, value=0

def test_compile_simultaneous_operations():
    """
    Tests compiling a morphism with two simultaneous operations on different
    channels, which should be merged into a single OASM call.
    """
    # Arrange
    # Turn on CH0 and CH1 at the same time
    m = ttl_on(CH0) | ttl_on(CH1)

    # Act
    calls = compile_to_oasm_calls(m)

    # Assert
    # Should be a single TTL_SET call
    assert len(calls) == 1

    call = calls[0]
    assert call.dsl_func == OASMFunction.TTL_SET
    
    # The mask should have bit 0 and bit 1 set (1 | 2 = 3)
    expected_mask = (1 << CH0.local_id) | (1 << CH1.local_id)
    assert call.args[0] == expected_mask

    # The value should also have bit 0 and bit 1 set for turning them on
    expected_value = (1 << CH0.local_id) | (1 << CH1.local_id)
    assert call.args[1] == expected_value

def test_compile_sequence_with_simultaneous_ops_and_wait():
    """
    Tests a sequence that contains both simultaneous operations and a wait.
    """
    # Arrange
    wait_us = 10.0
    m = (ttl_on(CH0) | ttl_on(CH1)) >> identity(wait_us) >> (ttl_off(CH0) | ttl_off(CH1))

    # Act
    calls = compile_to_oasm_calls(m)

    # Assert
    assert len(calls) == 3

    # 1. First call: turn CH0 and CH1 ON
    call1 = calls[0]
    assert call1.dsl_func == OASMFunction.TTL_SET
    expected_mask1 = (1 << CH0.local_id) | (1 << CH1.local_id)
    expected_value1 = (1 << CH0.local_id) | (1 << CH1.local_id)
    assert call1.args == (expected_mask1, expected_value1)

    # 2. Second call: WAIT
    call2 = calls[1]
    assert call2.dsl_func == OASMFunction.WAIT_US
    
    # The wait time is between the end of the first physical op and the
    # start of the second one.
    m_on = ttl_on(CH0) | ttl_on(CH1)
    expected_wait_cycles = m_on.total_duration_cycles + identity(wait_us).total_duration_cycles
    expected_wait_us = cycles_to_us(expected_wait_cycles)
    assert call2.args[0] == pytest.approx(expected_wait_us)

    # 3. Third call: turn CH0 and CH1 OFF
    call3 = calls[2]
    assert call3.dsl_func == OASMFunction.TTL_SET
    expected_mask3 = (1 << CH0.local_id) | (1 << CH1.local_id)
    expected_value3 = 0 # Both off
    assert call3.args == (expected_mask3, expected_value3)
