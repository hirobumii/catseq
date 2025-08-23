# tests/morphisms/test_common.py

"""
Test suite for the common morphism factories in `catseq/morphisms/common.py`.

This file tests the utility functions that create simple, common morphisms,
such as `Hold` and `Marker`.
"""

import pytest
from catseq.protocols import Channel, State
from catseq.model import IdentityMorphism
from catseq.morphisms.common import Hold, Marker, WaitOnTrigger, Call
from catseq.hardware.base import BaseHardware

# --- Test Fixtures ---

class MockHardware(BaseHardware):
    def validate_transition(self, from_state: State, to_state: State) -> None:
        pass

@pytest.fixture
def mock_channel():
    """Provides a mock channel for tests."""
    # Clear instances to ensure test isolation
    Channel._instances.clear()
    return Channel(name="mock_ch", hardware_type=MockHardware)

@pytest.fixture
def mock_state():
    """Provides a mock state for tests."""
    class MockState(State):
        pass
    return MockState()

# --- Tests for Hold() ---

def test_hold_creates_identity_morphism(mock_channel, mock_state):
    """
    Tests that Hold() correctly creates an IdentityMorphism with the right properties.
    """
    duration = 0.1
    m = Hold(mock_channel, mock_state, duration)

    assert isinstance(m, IdentityMorphism)
    assert m.duration == duration

    expected_domain = ((mock_channel, mock_state),)
    assert m.dom == expected_domain
    assert m.cod == expected_domain # For Identity, dom and cod are the same

@pytest.mark.parametrize("invalid_duration", [0, -0.1, -100])
def test_hold_raises_for_non_positive_duration(mock_channel, mock_state, invalid_duration):
    """
    Tests that Hold() raises a ValueError if the duration is not positive.
    """
    with pytest.raises(ValueError, match="Hold duration must be a positive number"):
        Hold(mock_channel, mock_state, invalid_duration)

# --- Tests for Marker() ---

def test_marker_creates_zero_duration_morphism(mock_channel, mock_state):
    """
    Tests that Marker() creates a zero-duration IdentityMorphism.
    """
    m = Marker(mock_channel, mock_state, "test_marker")

    assert isinstance(m, IdentityMorphism)
    assert m.duration == 0.0
    assert m.name == "Marker(test_marker)"

    expected_domain = ((mock_channel, mock_state),)
    assert m.dom == expected_domain
    assert m.cod == expected_domain

# --- Tests for Unimplemented Functions ---

@pytest.mark.parametrize("func", [WaitOnTrigger, Call])
def test_unimplemented_functions_raise_error(func):
    """
    Tests that placeholder functions raise NotImplementedError.
    """
    with pytest.raises(NotImplementedError):
        func()
