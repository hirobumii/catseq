# tests/morphisms/test_common.py

"""
Test suite for the common morphism factories in `catseq/morphisms/common.py`.

This file tests the utility functions that create simple, common morphisms,
such as `Hold` and `Marker`.
"""

import pytest
from catseq.protocols import Channel, State
from catseq.model import LaneMorphism, IdentityMorphism
from catseq.morphisms.common import hold, marker, wait_on_trigger, call
from catseq.hardware.base import BaseHardware
from catseq.builder import MorphismBuilder

# --- Test Fixtures ---

class MockHardware(BaseHardware):
    def validate_transition(self, from_state: State, to_state: State) -> None:
        pass

@pytest.fixture
def mock_channel():
    """Provides a mock channel for tests."""
    Channel._instances.clear()
    return Channel(name="mock_ch", hardware_type=MockHardware)

@pytest.fixture
def mock_state():
    """Provides a mock state for tests."""
    class MockState(State): pass
    return MockState()

# --- Tests for hold() ---

def test_hold_builder(mock_channel, mock_state):
    """
    Tests that hold() creates a builder that generates a correct hold morphism.
    """
    duration = 0.1

    # Create the builder
    hold_builder = hold(duration)
    assert isinstance(hold_builder, MorphismBuilder)

    # Execute the builder
    m = hold_builder(mock_channel, from_state=mock_state)

    assert isinstance(m, LaneMorphism)
    # The lane should contain a single IdentityMorphism
    primitive = m.lanes[mock_channel][0]
    assert isinstance(primitive, IdentityMorphism)
    assert m.duration == duration

    expected_domain = ((mock_channel, mock_state),)
    assert m.dom == expected_domain
    assert m.cod == expected_domain

@pytest.mark.parametrize("invalid_duration", [0, -0.1])
def test_hold_builder_invalid_duration(invalid_duration):
    """
    Tests that the hold() factory itself raises a ValueError for invalid duration.
    """
    with pytest.raises(ValueError, match="Hold duration must be a positive number"):
        hold(invalid_duration)

# --- Tests for marker() ---

def test_marker_builder(mock_channel, mock_state):
    """
    Tests that marker() creates a builder that generates a correct marker morphism.
    """
    marker_builder = marker("test_marker")
    assert isinstance(marker_builder, MorphismBuilder)

    m = marker_builder(mock_channel, from_state=mock_state)

    assert m.duration == 0.0
    primitive = m.lanes[mock_channel][0]
    assert isinstance(primitive, IdentityMorphism)
    assert primitive.name == "marker('test_marker')"
    assert m.dom == ((mock_channel, mock_state),)

# --- Tests for Unimplemented Functions ---

@pytest.mark.parametrize("func", [wait_on_trigger, call])
def test_unimplemented_functions_raise_error(func):
    """
    Tests that placeholder functions raise NotImplementedError.
    """
    with pytest.raises(NotImplementedError):
        func()
