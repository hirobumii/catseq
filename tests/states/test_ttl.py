# tests/states/test_ttl.py
"""
Test suite for `catseq/states/ttl.py`.
"""
import pytest
from dataclasses import is_dataclass, FrozenInstanceError
from catseq.core.protocols import State
from catseq.states.ttl import TTLState, TTLOn, TTLOff

def test_ttl_state_inheritance():
    """Tests that TTLState and its subclasses inherit from State."""
    assert issubclass(TTLState, State)
    assert issubclass(TTLOn, TTLState)
    assert issubclass(TTLOff, TTLState)

def test_ttl_states_are_dataclasses():
    """Tests that TTLOn and TTLOff are frozen dataclasses."""
    assert is_dataclass(TTLOn)
    assert is_dataclass(TTLOff)

    # Check if they are frozen
    on_instance = TTLOn()
    with pytest.raises(FrozenInstanceError):
        on_instance.some_attribute = "test"

    off_instance = TTLOff()
    with pytest.raises(FrozenInstanceError):
        off_instance.some_attribute = "test"

def test_ttl_state_equality():
    """Tests that instances of the same state are equal."""
    assert TTLOn() == TTLOn()
    assert TTLOff() == TTLOff()
    assert TTLOn() != TTLOff()
