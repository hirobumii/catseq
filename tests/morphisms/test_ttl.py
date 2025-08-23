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

def test_turn_off_invalid_state(ttl_channel):
    """Tests that turn_off raises TypeError for non-TTLState input."""
    with pytest.raises(TypeError, match="from_state for turn_off must be a TTLState"):
        turn_off(ttl_channel, Uninitialized())

def test_pulse_creates_lanemorphism(ttl_channel):
    """
    Tests that the pulse() factory correctly composes a LaneMorphism.
    A pulse should be composed of three primitive morphisms:
    1. turn_on:  TTLOutputOff -> TTLOutputOn
    2. Hold:     Holds TTLOutputOn for the specified duration.
    3. turn_off: TTLOutputOn -> TTLOutputOff
    """
    start_state = TTLOutputOff()
    hold_duration = 100e-9
    # Note the new argument order
    m = pulse(ttl_channel, duration=hold_duration, from_state=start_state)

    # Check the overall structure
    assert isinstance(m, LaneMorphism)
    # The lane for our channel should contain the three composed primitives
    assert len(m.lanes[ttl_channel]) == 3

    # Check the initial and final states of the composite morphism
    final_dom_state = m.dom[0][1]
    final_cod_state = m.cod[0][1]
    assert final_dom_state == start_state
    assert final_cod_state == TTLOutputOff()

    # Check the total duration
    expected_duration = (2 * SINGLE_CYCLE_DURATION_S) + hold_duration
    assert m.duration == pytest.approx(expected_duration)

def test_pulse_invalid_duration(ttl_channel):
    """Tests that pulse raises ValueError for non-positive duration."""
    with pytest.raises(ValueError, match="Pulse hold duration must be a positive number."):
        pulse(ttl_channel, duration=0)

    with pytest.raises(ValueError, match="Pulse hold duration must be a positive number."):
        pulse(ttl_channel, duration=-100e-9)

def test_turn_on_off_with_default_state(ttl_channel):
    """
    Tests that turn_on/turn_off use the correct default from_state.
    """
    # turn_on should default to a from_state of TTLOutputOff
    m_on = turn_on(ttl_channel)
    assert m_on.dom == ((ttl_channel, TTLOutputOff()),)
    assert m_on.cod == ((ttl_channel, TTLOutputOn()),)

    # turn_off should default to a from_state of TTLOutputOn
    m_off = turn_off(ttl_channel)
    assert m_off.dom == ((ttl_channel, TTLOutputOn()),)
    assert m_off.cod == ((ttl_channel, TTLOutputOff()),)

def test_pulse_with_default_state(ttl_channel):
    """
    Tests that pulse() uses the correct default from_state.
    """
    m = pulse(ttl_channel, duration=1e-6)
    # The composite morphism should start from the default, which is TTLOutputOff
    assert m.dom == ((ttl_channel, TTLOutputOff()),)
    # And it should end back in the Off state
    assert m.cod == ((ttl_channel, TTLOutputOff()),)

def test_logical_validation_errors(ttl_channel):
    """
    Tests that logical errors (e.g. turning on an already-on channel)
    are caught and raise ValueErrors.
    """
    # Test turning on a channel that is already on
    with pytest.raises(ValueError, match="Cannot turn_on a channel that is already On"):
        turn_on(ttl_channel, from_state=TTLOutputOn())

    # Test turning off a channel that is already off
    with pytest.raises(ValueError, match="Cannot turn_off a channel that is already Off"):
        turn_off(ttl_channel, from_state=TTLOutputOff())

    # Test pulsing a channel that is already on
    with pytest.raises(ValueError, match="Cannot pulse a channel that is already On"):
        pulse(ttl_channel, duration=1e-6, from_state=TTLOutputOn())
