# tests/hardware/test_base.py

"""
Test suite for `catseq/hardware/base.py`.

This file tests the base components for hardware definitions, primarily the
abstract base class `BaseHardware`.
"""

import pytest
from catseq.protocols import State
from catseq.hardware.base import BaseHardware

# --- Test Fixture ---

class ConcreteHardware(BaseHardware):
    """A concrete implementation of BaseHardware for testing."""
    def validate_transition(self, from_state: State, to_state: State) -> None:
        """A minimal implementation for the abstract method."""
        pass

# --- Tests ---

def test_base_hardware_properties():
    """
    Tests that the properties of a BaseHardware subclass are set correctly.
    """
    hardware_name = "test_device"
    device = ConcreteHardware(name=hardware_name)

    assert device.name == hardware_name

def test_base_hardware_repr():
    """
    Tests the __repr__ method for a clear string representation.
    """
    device = ConcreteHardware(name="repr_device")
    expected_repr = "<ConcreteHardware: repr_device>"
    assert repr(device) == expected_repr

def test_cannot_instantiate_abstract_base_hardware():
    """
    Verifies that the abstract BaseHardware class cannot be instantiated directly.
    Attempting to do so should raise a TypeError.
    """
    with pytest.raises(TypeError, match="Can't instantiate abstract class BaseHardware"):
        BaseHardware(name="abstract_device")
