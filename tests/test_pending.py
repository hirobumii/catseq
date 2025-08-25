from dataclasses import dataclass
from typing import Union

from catseq.protocols import State
from catseq.pending import PENDING, PendingType, fill_in_pending_state

# --- Test Fixtures and Dummy Classes ---


@dataclass(frozen=True)
class StateSimple(State):
    """A simple state with one pending-capable field."""

    value: Union[int, PendingType] = PENDING


@dataclass(frozen=True)
class StateComplex(State):
    """A more complex state with multiple fields."""

    freq: Union[float, PendingType] = PENDING
    amp: Union[float, PendingType] = PENDING
    name: str = "default"


@dataclass(frozen=True)
class SourceState(State):
    """A state to be used as the source of truth."""

    freq: float
    amp: float
    extra_field: str = "extra"


# --- Test Cases for fill_in_pending_state ---


def test_fill_single_pending_field():
    """Tests that a single PENDING field is correctly filled."""
    template = StateSimple(value=PENDING)
    source = StateSimple(value=10)

    result = fill_in_pending_state(template, source)

    assert isinstance(result, StateSimple)
    assert result.value == 10


def test_fill_multiple_pending_fields():
    """Tests that multiple PENDING fields are correctly filled from a source."""
    template = StateComplex(freq=PENDING, amp=PENDING)
    source = SourceState(freq=123.45, amp=0.5)

    result = fill_in_pending_state(template, source)

    assert isinstance(result, StateComplex)
    assert result.freq == 123.45
    assert result.amp == 0.5
    assert result.name == "default"  # Unrelated field should be unchanged


def test_no_pending_fields_returns_original():
    """Tests that a state with no PENDING fields is returned unchanged."""
    template = StateSimple(value=5)
    source = StateSimple(value=10)

    result = fill_in_pending_state(template, source)

    assert result is template  # Should be the exact same object
    assert result.value == 5


def test_source_missing_attribute_returns_original():
    """
    Tests that if the source state lacks the needed attribute, the template
    is returned unchanged.
    """
    template = StateComplex(freq=PENDING)
    # Source state does not have a 'freq' attribute
    source = StateSimple(value=10)

    result = fill_in_pending_state(template, source)

    assert result is template
    assert result.freq is PENDING


def test_non_dataclass_input_is_handled():
    """Tests that non-dataclass inputs are returned unchanged."""
    template = "not a dataclass"
    source = StateSimple(10)

    result = fill_in_pending_state(template, source)
    assert result is template


def test_partial_fill():
    """Tests that only PENDING fields are filled, leaving others."""
    template = StateComplex(freq=PENDING, amp=0.99)  # amp is not PENDING
    source = SourceState(freq=123.45, amp=0.5)

    result = fill_in_pending_state(template, source)

    assert isinstance(result, StateComplex)
    assert result.freq == 123.45  # This should be filled
    assert result.amp == 0.99  # This should NOT be changed
