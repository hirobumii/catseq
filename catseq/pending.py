import dataclasses
from typing import Type, Any
from catseq.protocols import State

# --- Sentinel Value for Pending Fields ---

class PendingType:
    """A unique type for the PENDING sentinel value."""
    def __repr__(self) -> str:
        return "PENDING"

PENDING = PendingType()
"""
A sentinel value used to mark fields in a State dataclass as "pending".
These fields are intended to be inferred from a preceding state during composition.
"""

# --- State Inference Logic ---

def fill_in_pending_state(template_state: State, source_state: State) -> State:
    """
    Fills in pending fields of a template state from a source state.

    This function inspects a 'template_state' for fields marked with the PENDING
    sentinel. For each pending field, it looks for a field with the same name
    in the 'source_state' and uses its value to create a new, filled state object.

    Args:
        template_state: The state object that may contain PENDING fields.
        source_state: The state object to draw values from.

    Returns:
        A new state object with pending fields filled, or the original
        template_state if no fields were filled.
    """
    if not dataclasses.is_dataclass(template_state) or not isinstance(template_state, State):
        return template_state

    updates: dict[str, Any] = {}

    # Iterate over the fields defined in the dataclass
    for field_info in dataclasses.fields(template_state):
        field_name = field_info.name
        template_value = getattr(template_state, field_name)

        # If the field is marked as PENDING, try to fill it
        if template_value is PENDING:
            if hasattr(source_state, field_name):
                source_value = getattr(source_state, field_name)
                # Avoid filling with another PENDING or None, which could be ambiguous
                if source_value is not PENDING and source_value is not None:
                    updates[field_name] = source_value

    # If we found any fields to update, create a new state object
    if updates:
        return dataclasses.replace(template_state, **updates)

    # Otherwise, return the original state object
    return template_state
