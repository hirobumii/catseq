"""
AtomicMorphism factories.

This module provides factory functions for creating AtomicMorphism objects,
which are the fundamental building blocks of sequences.
"""
from typing import List, Union

from .morphism import Morphism, from_atomic
from .time_utils import us_to_cycles
from .types.common import Channel, OperationType, AtomicMorphism, State
from .types.ttl import TTLState
from .types.rwg import (
    RWGActive,
    RWGReady,
    RWGUninitialized,
    WaveformParams,
    RWGWaveformInstruction,
)

def ttl_init(channel: Channel, initial_state: TTLState = TTLState.OFF) -> Morphism:
    """Creates a TTL initialization morphism."""
    op = AtomicMorphism(
        channel=channel,
        start_state=None,
        end_state=initial_state,
        duration_cycles=2,
        operation_type=OperationType.TTL_INIT
    )
    return from_atomic(op)

def ttl_on(channel: Channel) -> Morphism:
    """Creates a TTL ON morphism."""
    op = AtomicMorphism(
        channel=channel,
        start_state=TTLState.OFF,
        end_state=TTLState.ON,
        duration_cycles=1,
        operation_type=OperationType.TTL_ON
    )
    return from_atomic(op)

def ttl_off(channel: Channel) -> Morphism:
    """Creates a TTL OFF morphism."""
    op = AtomicMorphism(
        channel=channel,
        start_state=TTLState.ON,
        end_state=TTLState.OFF,
        duration_cycles=1,
        operation_type=OperationType.TTL_OFF
    )
    return from_atomic(op)

def rwg_init(channel: Channel, carrier_freq: float) -> Morphism:
    """Creates an RWG initialization morphism."""
    op = AtomicMorphism(
        channel=channel,
        start_state=RWGUninitialized(),
        end_state=RWGReady(carrier_freq=carrier_freq, rf_on=False),
        duration_cycles=2,
        operation_type=OperationType.RWG_INIT,
    )
    return from_atomic(op)

def rwg_load_coeffs(
    channel: Channel,
    params: List[WaveformParams],
    start_state: Union[RWGReady, RWGActive],
) -> Morphism:
    """Creates a morphism to load RWG waveform coefficients."""
    if not isinstance(start_state, (RWGReady, RWGActive)):
        raise TypeError(f"RWG load_coeffs must start from RWGReady or RWGActive, not {type(start_state)}")

    op = AtomicMorphism(
        channel=channel,
        start_state=start_state,
        end_state=RWGWaveformInstruction(params=params),
        duration_cycles=0,
        operation_type=OperationType.RWG_LOAD_COEFFS,
    )
    return from_atomic(op)

def rwg_update_params(
    channel: Channel, duration_us: float, start_state: RWGWaveformInstruction, end_state: RWGActive
) -> Morphism:
    """Creates a morphism to trigger an RWG parameter update (a ramp)."""
    duration_cycles = us_to_cycles(duration_us)
    op = AtomicMorphism(
        channel=channel,
        start_state=start_state,
        end_state=end_state,
        duration_cycles=duration_cycles,
        operation_type=OperationType.RWG_UPDATE_PARAMS,
    )
    return from_atomic(op)