import pytest
from catseq.model import PrimitiveMorphism, LaneMorphism
from catseq.states.common import Uninitialized
from catseq.states.ttl import TTLOutputOn, TTLOutputOff
from catseq.morphisms import ttl
from catseq.builder import MorphismBuilder


def test_initialize_builder(ttl_channel):
    """Tests the initialize builder returns a consistent morphism."""
    init_builder = ttl.initialize()
    assert isinstance(init_builder, MorphismBuilder)

    m = init_builder(ttl_channel) # from_state defaults to Uninitialized

    primitive = m.lanes[ttl_channel][0]
    assert isinstance(primitive, PrimitiveMorphism)
    assert m.dom == ((ttl_channel, Uninitialized()),)
    assert m.cod == ((ttl_channel, TTLOutputOff()),)
    assert m.duration == ttl.SINGLE_CYCLE_DURATION_S

def test_turn_on_builder(ttl_channel):
    """Tests the turn_on builder."""
    on_builder = ttl.turn_on()
    assert isinstance(on_builder, MorphismBuilder)

    m = on_builder(ttl_channel, from_state=TTLOutputOff())
    assert m.dom == ((ttl_channel, TTLOutputOff()),)
    assert m.cod == ((ttl_channel, TTLOutputOn()),)

def test_turn_on_invalid_state_types(ttl_channel):
    """Tests that the turn_on generator raises TypeError for non-TTLState input."""
    on_builder = ttl.turn_on()
    with pytest.raises(TypeError, match="from_state for turn_on must be a TTLState"):
        on_builder(ttl_channel, from_state=Uninitialized())

def test_turn_off_builder(ttl_channel):
    """Tests the turn_off builder."""
    off_builder = ttl.turn_off()
    assert isinstance(off_builder, MorphismBuilder)

    m = off_builder(ttl_channel, from_state=TTLOutputOn())
    assert m.dom == ((ttl_channel, TTLOutputOn()),)
    assert m.cod == ((ttl_channel, TTLOutputOff()),)

def test_pulse_builder(ttl_channel):
    """
    Tests that the pulse() builder correctly composes a LaneMorphism.
    """
    hold_duration = 100e-9
    pulse_builder = ttl.pulse(hold_duration)
    assert isinstance(pulse_builder, MorphismBuilder)

    # Execute the builder, starting from the Off state
    m = pulse_builder(ttl_channel, from_state=TTLOutputOff())

    assert isinstance(m, LaneMorphism)
    assert len(m.lanes[ttl_channel]) == 3, "Pulse should be composed of 3 primitives"

    assert m.dom == ((ttl_channel, TTLOutputOff()),)
    assert m.cod == ((ttl_channel, TTLOutputOff()),)

    expected_duration = (2 * ttl.SINGLE_CYCLE_DURATION_S) + hold_duration
    assert m.duration == pytest.approx(expected_duration)

def test_pulse_invalid_duration():
    """Tests that the pulse() factory raises ValueError for non-positive duration."""
    with pytest.raises(ValueError, match="Pulse hold duration must be a positive number."):
        ttl.pulse(duration=0)

    with pytest.raises(ValueError, match="Pulse hold duration must be a positive number."):
        ttl.pulse(duration=-100e-9)

def test_factories_have_correct_defaults(ttl_channel):
    """
    Tests that the morphism builders have the correct default from_state,
    and that calling them without a state works as expected.
    """
    # Check the default state property on the builder
    assert ttl.initialize().default_from_state == Uninitialized()
    assert ttl.turn_on().default_from_state == TTLOutputOff()
    assert ttl.turn_off().default_from_state == TTLOutputOn()
    assert ttl.pulse(1e-6).default_from_state == TTLOutputOff()

    # Check that calling with no from_state works
    m_on = ttl.turn_on()(ttl_channel)
    assert m_on.dom == ((ttl_channel, TTLOutputOff()),)

    m_off = ttl.turn_off()(ttl_channel)
    assert m_off.dom == ((ttl_channel, TTLOutputOn()),)

    m_pulse = ttl.pulse(1e-6)(ttl_channel)
    assert m_pulse.dom == ((ttl_channel, TTLOutputOff()),)

def test_logical_validation_errors(ttl_channel):
    """
    Tests that logical errors (e.g. turning on an already-on channel)
    are caught and raise ValueErrors at execution time.
    """
    # Test turning on a channel that is already on
    with pytest.raises(ValueError, match="Cannot turn_on a channel that is already On"):
        ttl.turn_on()(ttl_channel, from_state=TTLOutputOn())

    # Test turning off a channel that is already off
    with pytest.raises(ValueError, match="Cannot turn_off a channel that is already Off"):
        ttl.turn_off()(ttl_channel, from_state=TTLOutputOff())

    # Test pulsing a channel that is already on. The error should come from the
    # underlying `turn_on` call.
    with pytest.raises(ValueError, match="Cannot turn_on a channel that is already On"):
        ttl.pulse(duration=1e-6)(ttl_channel, from_state=TTLOutputOn())
