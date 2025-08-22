import pytest
from catseq.protocols import State, Channel
from catseq.model import PrimitiveMorphism, LaneMorphism
from catseq.states.common import Uninitialized
from catseq.states.ttl import TTLState, TTLOutputOn, TTLOutputOff
from catseq.morphisms.ttl import (
    initialize,
    turn_on,
    turn_off,
    pulse,
    SINGLE_CYCLE_DURATION_S,
)

# All fixtures are now in conftest.py

def test_initialize(ttl_channel):
    """Tests the initialize morphism factory returns a consistent PrimitiveMorphism."""
    m = initialize(ttl_channel)
    assert isinstance(m, PrimitiveMorphism)
    assert m.channel == ttl_channel
    assert m.dom == ((ttl_channel, Uninitialized()),)
    assert m.cod == ((ttl_channel, TTLOutputOff()),)
    assert m.duration == SINGLE_CYCLE_DURATION_S

def test_turn_on(ttl_channel):
    """Tests the turn_on morphism factory."""
    start_state = TTLOutputOff()
    m = turn_on(ttl_channel, start_state)
    assert isinstance(m, PrimitiveMorphism)
    assert m.dom == ((ttl_channel, start_state),)
    assert m.cod == ((ttl_channel, TTLOutputOn()),)

def test_turn_on_invalid_state(ttl_channel):
    """Tests that turn_on raises TypeError for non-TTLState input."""
    with pytest.raises(TypeError, match="from_state for turn_on must be a TTLState"):
        turn_on(ttl_channel, Uninitialized())

def test_turn_off(ttl_channel):
    """Tests the turn_off morphism factory."""
    start_state = TTLOutputOn()
    m = turn_off(ttl_channel, start_state)
    assert isinstance(m, PrimitiveMorphism)
    assert m.dom == ((ttl_channel, start_state),)
    assert m.cod == ((ttl_channel, TTLOutputOff()),)

def test_pulse_creates_lanemorphism(ttl_channel):
    """Tests that a pulse composes into a LaneMorphism."""
    start_state = TTLOutputOff()
    hold_duration = 100e-9
    m = pulse(ttl_channel, start_state, duration=hold_duration)

    assert isinstance(m, LaneMorphism)
    assert len(m.lanes[ttl_channel]) == 3

    final_dom_state = m.dom[0][1]
    final_cod_state = m.cod[0][1]
    assert final_dom_state == start_state
    assert final_cod_state == TTLOutputOff()

    expected_duration = (2 * SINGLE_CYCLE_DURATION_S) + hold_duration
    assert m.duration == pytest.approx(expected_duration)

def test_pulse_invalid_duration(ttl_channel):
    """Tests that pulse raises ValueError for non-positive duration."""
    with pytest.raises(ValueError, match="Pulse hold duration must be a positive number."):
        pulse(ttl_channel, TTLOutputOff(), duration=0)

    with pytest.raises(ValueError, match="Pulse hold duration must be a positive number."):
        pulse(ttl_channel, TTLOutputOff(), duration=-100e-9)
