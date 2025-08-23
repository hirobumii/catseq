# tests/states/test_ttl.py

"""
Test suite for TTL states defined in `catseq/states/ttl.py`.

This file tests the data classes for Transistor-Transistor Logic (TTL)
states, including:
- `TTLState`: The base state for TTL.
- `TTLInput`: Represents the input state.
- `TTLOutputOn`: Represents the high-voltage state.
- `TTLOutputOff`: Represents the low-voltage state.

Tests verify correct instantiation, subclassing, and immutability.
"""

import pytest
from dataclasses import FrozenInstanceError
from catseq.protocols import State
from catseq.states.ttl import TTLState, TTLInput, TTLOutputOn, TTLOutputOff

@pytest.mark.parametrize("ttl_class", [
    TTLInput,
    TTLOutputOn,
    TTLOutputOff,
])
def test_ttl_states(ttl_class):
    """
    Tests the properties of the concrete TTL state classes.
    - They should be subclasses of TTLState and State.
    - They should be instantiable.
    - They must be immutable (frozen).
    """
    # Verify subclassing
    assert issubclass(ttl_class, TTLState)
    assert issubclass(ttl_class, State)

    # Instantiate the state
    state_instance = ttl_class()
    assert isinstance(state_instance, ttl_class)

    # Verify that it is frozen (immutable)
    with pytest.raises(FrozenInstanceError):
        state_instance.new_attribute = "test" # type: ignore
