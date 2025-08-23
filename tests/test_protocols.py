# tests/test_protocols.py

"""
Test suite for the core protocols defined in `catseq/protocols.py`.

This file contains tests for the fundamental abstract base classes and protocols
that form the foundation of the Cat-SEQ framework, such as:
- State: The base class for all hardware states.
- Channel: The base class for all hardware channel identifiers.
"""

import pytest
from dataclasses import dataclass, FrozenInstanceError
from catseq import protocols

# --- Test Fixtures and Mocks ---

class MockHardware(protocols.HardwareInterface):
    """A mock implementation of the HardwareInterface for testing."""
    def __init__(self, name: str):
        self.name = name
        self.validate_transition_calls = []

    def validate_transition(self, from_state: protocols.State, to_state: protocols.State) -> None:
        """Mock validation method."""
        self.validate_transition_calls.append((from_state, to_state))

# --- Tests for State ---

def test_state_subclass_is_immutable_when_decorated():
    """
    Tests that subclasses of State are immutable if also decorated as frozen.
    The @dataclass(frozen=True) decorator is not automatically inherited in its
    effect, so subclasses must be explicitly decorated. This test verifies
    the intended usage pattern.
    """
    # Define a concrete state that is properly decorated.
    @dataclass(frozen=True)
    class MyState(protocols.State):
        value: int

    s = MyState(value=1)
    with pytest.raises(FrozenInstanceError):
        # This attempt to mutate the instance must fail.
        s.value = 2 # type: ignore

# --- Tests for Channel ---

def test_channel_is_singleton():
    """
    Tests the singleton behavior of the Channel class.
    Ensures that creating a channel with the same name multiple times returns
    the exact same object instance.
    """
    # Clear the singleton registry before the test to ensure isolation
    protocols.Channel._instances.clear()

    ch1 = protocols.Channel("TTL_0", MockHardware)
    ch2 = protocols.Channel("TTL_0", MockHardware)

    assert ch1 is ch2, "Channels with the same name should be the same object."

def test_channel_properties_and_initialization():
    """
    Tests that Channel properties are correctly initialized and accessible.
    - The `name` property should return the channel's name.
    - The `instance` property should hold a correctly instantiated hardware object.
    - The `__init__` method should not re-initialize an existing singleton.
    """
    protocols.Channel._instances.clear()

    ch = protocols.Channel("DAC_1", MockHardware)

    # Test properties
    assert ch.name == "DAC_1"
    assert isinstance(ch.instance, MockHardware)
    assert ch.instance.name == "DAC_1"

    # Try to "re-initialize" with different hardware, which should be ignored
    class AnotherMockHardware(protocols.HardwareInterface):
        def __init__(self, name: str): pass
        def validate_transition(self, from_state: protocols.State, to_state: protocols.State) -> None: pass

    ch_same = protocols.Channel("DAC_1", AnotherMockHardware)

    assert ch_same is ch
    assert isinstance(ch.instance, MockHardware), "Hardware instance should not have been replaced."

def test_channel_equality_and_hash():
    """
    Tests the equality and hashing logic of the Channel class.
    - Channels with the same name should be equal and have the same hash.
    - Channels with different names should not be equal.
    - A channel should not be equal to an object of a different type.
    """
    protocols.Channel._instances.clear()

    ch_a1 = protocols.Channel("A", MockHardware)
    ch_a2 = protocols.Channel("A", MockHardware)
    ch_b = protocols.Channel("B", MockHardware)

    # Equality
    assert ch_a1 == ch_a2
    assert ch_a1 != ch_b
    assert ch_a1 != "not a channel"

    # Hashing
    assert hash(ch_a1) == hash(ch_a2)
    assert hash(ch_a1) != hash(ch_b)

    # Usability in a dictionary/set
    channel_set = {ch_a1, ch_a2, ch_b}
    assert len(channel_set) == 2
    assert ch_a1 in channel_set
    assert ch_b in channel_set

def test_channel_repr():
    """
    Tests the __repr__ method for a clear string representation.
    """
    protocols.Channel._instances.clear()
    ch = protocols.Channel("TEST_CH", MockHardware)
    assert repr(ch) == "<Channel: TEST_CH>"

def test_channel_constructor_error_handling():
    """
    Tests that the Channel constructor raises TypeErrors for invalid arguments.
    """
    protocols.Channel._instances.clear()

    # Test for non-string name
    with pytest.raises(TypeError):
        protocols.Channel(123, MockHardware)

    # Test for non-callable hardware_type
    with pytest.raises(TypeError, match="'int' object is not callable"):
        protocols.Channel("test", 123)

    # Test for hardware_type with incorrect __init__ signature
    class BadHardware:
        def __init__(self): pass # Does not accept 'name'

    with pytest.raises(TypeError, match=r"__init__\(\) got an unexpected keyword argument 'name'"):
        protocols.Channel("test_bad_hw", BadHardware)
