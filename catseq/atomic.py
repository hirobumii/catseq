"""
AtomicMorphism factories.

This module provides factory functions for creating AtomicMorphism objects,
which are the fundamental building blocks of sequences.
"""
from .morphism import Morphism, from_atomic
from .time_utils import us_to_cycles
from .types import Channel, OperationType, TTLState, AtomicMorphism


def ttl_init(channel: Channel, initial_state: TTLState = TTLState.OFF) -> Morphism:
    """Creates a TTL initialization morphism."""
    op = AtomicMorphism(
        channel=channel,
        start_state=None,
        end_state=initial_state,
        duration_cycles=2,  # 2 cycles for initialization (sfs + amk)
        operation_type=OperationType.TTL_INIT
    )
    return from_atomic(op)

def ttl_on(channel: Channel) -> Morphism:
    """Creates a TTL ON morphism."""
    op = AtomicMorphism(
        channel=channel,
        start_state=TTLState.OFF,
        end_state=TTLState.ON,
        duration_cycles=1,  # 1 cycle for state change
        operation_type=OperationType.TTL_ON
    )
    return from_atomic(op)

def ttl_off(channel: Channel) -> Morphism:
    """Creates a TTL OFF morphism."""
    op = AtomicMorphism(
        channel=channel,
        start_state=TTLState.ON,
        end_state=TTLState.OFF,
        duration_cycles=1,  # 1 cycle for state change
        operation_type=OperationType.TTL_OFF
    )
    return from_atomic(op)

def identity(duration_us: float) -> Morphism:
    """Creates a channelless identity morphism (a pure wait)."""
    duration_cycles = us_to_cycles(duration_us)
    if duration_cycles < 0:
        raise ValueError("Identity duration must be non-negative.")
    # The Morphism constructor is needed here for the special channelless case
    return Morphism(lanes={}, _duration_cycles=duration_cycles)
