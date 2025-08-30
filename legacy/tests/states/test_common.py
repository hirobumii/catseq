# tests/states/test_common.py

"""
Test suite for common states defined in `catseq/states/common.py`.

This file tests the `Uninitialized` state class. Since it's a simple
data class, tests primarily focus on:
- Ensuring it can be instantiated correctly.
- Verifying it is a subclass of `protocols.State`.
- Confirming its immutability (`frozen=True`).
"""

import pytest
from dataclasses import FrozenInstanceError
from catseq.protocols import State
from catseq.states.common import Uninitialized


def test_uninitialized_state():
    """
    Tests the properties of the Uninitialized state.
    - It should be a subclass of State.
    - It should be instantiable.
    - It must be immutable (frozen).
    """
    # Verify it is a subclass of the base State
    assert issubclass(Uninitialized, State)

    # Instantiate the state
    uninitialized_state = Uninitialized()
    assert isinstance(uninitialized_state, Uninitialized)

    # Verify that it is frozen (immutable)
    with pytest.raises(FrozenInstanceError):
        uninitialized_state.new_attribute = "test"  # type: ignore
