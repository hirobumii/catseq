# tests/hardware/test_ttl.py

"""
Test suite for the TTL hardware rules defined in `catseq/hardware/ttl.py`.

This file contains tests for the `TTLDevice` class, focusing on its
validation logic for state transitions. The TTL hardware is simpler than others,
so tests primarily cover:
- Validation of legal state transitions (e.g., Uninitialized -> TTLOutputOn).
- Rejection of illegal state transitions involving incompatible state types.
"""

import pytest
from catseq.hardware.ttl import TTLDevice
from catseq.states.common import Uninitialized
from catseq.states.ttl import TTLOutputOn, TTLOutputOff
from catseq.protocols import State

# --- Test Fixtures ---


@pytest.fixture
def ttl_device():
    """Provides a default TTLDevice instance for tests."""
    return TTLDevice(name="test_ttl")


class NotARealState(State):
    """A dummy state class for testing invalid transitions."""

    pass


# --- Tests for Legal Transitions ---


@pytest.mark.parametrize(
    "from_state, to_state",
    [
        (Uninitialized(), TTLOutputOn()),
        (Uninitialized(), TTLOutputOff()),
        (TTLOutputOn(), TTLOutputOff()),
        (TTLOutputOff(), TTLOutputOn()),
    ],
)
def test_ttl_legal_transitions(ttl_device, from_state, to_state):
    """
    Tests that `validate_transition` allows legal transitions between valid
    TTL states and from the Uninitialized state. It should not raise any error.
    """
    try:
        ttl_device.validate_transition(from_state, to_state)
    except TypeError:
        pytest.fail(
            f"Legal transition {from_state} -> {to_state} was incorrectly rejected."
        )


# --- Tests for Illegal Transitions ---


def test_ttl_illegal_to_state(ttl_device):
    """
    Tests that `validate_transition` raises a TypeError if the target state
    is not a valid TTLState.
    """
    with pytest.raises(TypeError, match="Invalid target stage"):
        ttl_device.validate_transition(Uninitialized(), NotARealState())


def test_ttl_illegal_from_state(ttl_device):
    """
    Tests that `validate_transition` raises a TypeError if the source state
    is not Uninitialized or a valid TTLState.
    """
    with pytest.raises(TypeError, match="Invalid source stage"):
        ttl_device.validate_transition(NotARealState(), TTLOutputOn())
