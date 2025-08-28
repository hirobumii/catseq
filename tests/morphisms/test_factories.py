# tests/morphisms/test_factories.py
"""
Test suite for the refactored morphism factory functions.
"""
import pytest
from catseq.core import (
    Channel, State, Morphism, AtomicOperation
)
from catseq.hardware.ttl import TTLDevice
from catseq.states.common import Uninitialized
from catseq.states.ttl import TTLOn, TTLOff
from catseq.morphisms.common import hold
from catseq.morphisms.ttl import pulse, initialize

# --- Fixtures ---

@pytest.fixture
def ttl_ch() -> Channel:
    """Provides a standard TTL channel for tests."""
    # Clear instances to ensure isolation between tests
    if "ttl_test_ch" in Channel._instances:
        del Channel._instances["ttl_test_ch"]
    return Channel("ttl_test_ch", TTLDevice("ttl_test_ch"))

# --- Tests for common.hold() ---

def test_hold_creates_correct_morphism(ttl_ch):
    """Tests that hold() creates a valid Morphism."""
    duration = 0.1
    state = TTLOn()
    m = hold(ttl_ch, state, duration)

    assert isinstance(m, Morphism)
    assert m.duration == duration
    assert m.dom.get_state(ttl_ch) == state
    assert m.cod.get_state(ttl_ch) == state

    # Check the atomic operations
    ops = m.get_lane_operations(ttl_ch)
    assert len(ops) == 1
    op = ops[0]
    assert isinstance(op, AtomicOperation)
    assert op.from_state == state
    assert op.to_state == state
    assert op.duration == duration

def test_hold_invalid_duration(ttl_ch):
    """Tests that hold() raises ValueError for non-positive duration."""
    with pytest.raises(ValueError, match="Hold duration must be a positive number"):
        hold(ttl_ch, TTLOn(), 0)
    with pytest.raises(ValueError, match="Hold duration must be a positive number"):
        hold(ttl_ch, TTLOn(), -1.0)

# --- Tests for ttl.pulse() ---

def test_pulse_creates_correct_morphism(ttl_ch):
    """Tests that pulse() creates a valid OFF -> ON -> OFF pulse morphism."""
    duration = 1e-6
    m = pulse(ttl_ch, duration)

    assert isinstance(m, Morphism)
    assert m.duration == duration
    assert m.dom.get_state(ttl_ch) == TTLOff()
    assert m.cod.get_state(ttl_ch) == TTLOff()

    # Check the atomic operations: should be 3 ops
    ops = m.get_lane_operations(ttl_ch)
    assert len(ops) == 3

    # 1. Turn ON (instantaneous)
    assert ops[0].from_state == TTLOff()
    assert ops[0].to_state == TTLOn()
    assert ops[0].duration == 0.0

    # 2. Hold ON
    assert ops[1].from_state == TTLOn()
    assert ops[1].to_state == TTLOn()
    assert ops[1].duration == duration

    # 3. Turn OFF (instantaneous)
    assert ops[2].from_state == TTLOn()
    assert ops[2].to_state == TTLOff()
    assert ops[2].duration == 0.0

def test_pulse_invalid_duration(ttl_ch):
    """Tests that pulse() raises ValueError for non-positive duration."""
    with pytest.raises(ValueError, match="Pulse duration must be positive"):
        pulse(ttl_ch, 0)
    with pytest.raises(ValueError, match="Pulse duration must be positive"):
        pulse(ttl_ch, -1.0)

# --- Tests for ttl.initialize() ---

def test_initialize_creates_correct_morphism(ttl_ch):
    """Tests that initialize() creates a valid Uninitialized -> OFF morphism."""
    m = initialize(ttl_ch)

    assert isinstance(m, Morphism)
    assert m.duration == 0.0
    assert m.dom.get_state(ttl_ch) == Uninitialized()
    assert m.cod.get_state(ttl_ch) == TTLOff()

    ops = m.get_lane_operations(ttl_ch)
    assert len(ops) == 1
    op = ops[0]
    assert op.from_state == Uninitialized()
    assert op.to_state == TTLOff()
    assert op.duration == 0.0

def test_initialize_to_on_state(ttl_ch):
    """Tests that initialize() can also initialize to the ON state."""
    m = initialize(ttl_ch, initial_state=TTLOn())
    assert m.cod.get_state(ttl_ch) == TTLOn()
    assert m.get_lane_operations(ttl_ch)[0].to_state == TTLOn()

class NotTTLState(State):
    pass

def test_initialize_invalid_state(ttl_ch):
    """Tests that initialize() raises an error for a non-TTL target state."""
    with pytest.raises(TypeError):
        initialize(ttl_ch, initial_state=NotTTLState())
