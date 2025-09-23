"""
AtomicMorphism factories.

This module provides factory functions for creating AtomicMorphism objects,
which are the fundamental building blocks of sequences.
"""
from typing import List, Union

from .morphism import Morphism, from_atomic
from .time_utils import us_to_cycles, time_to_cycles
from .types.common import Channel, OperationType, AtomicMorphism, State
from .types.ttl import TTLState
from .types.rwg import (
    RWGActive,
    RWGReady,
    RWGUninitialized,
    WaveformParams,
    StaticWaveform,
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

def ttl_on(channel: Channel, start_state: State = TTLState.OFF) -> Morphism:
    """Creates a TTL ON morphism."""
    op = AtomicMorphism(
        channel=channel,
        start_state=start_state,
        end_state=TTLState.ON,
        duration_cycles=1,
        operation_type=OperationType.TTL_ON
    )
    return from_atomic(op)

def ttl_off(channel: Channel, start_state: State = TTLState.ON) -> Morphism:
    """Creates a TTL OFF morphism."""
    op = AtomicMorphism(
        channel=channel,
        start_state=start_state,
        end_state=TTLState.OFF,
        duration_cycles=1,
        operation_type=OperationType.TTL_OFF
    )
    return from_atomic(op)

def rwg_board_init(channel: Channel) -> Morphism:
    """Creates an RWG board-level initialization morphism (atomic operation)."""
    op = AtomicMorphism(
        channel=channel,
        start_state=RWGUninitialized(),
        end_state=RWGUninitialized(),  # Still uninitialized until carrier is set
        duration_cycles=0,  # Instantaneous operation, handled during global sync
        operation_type=OperationType.RWG_INIT,
    )
    return from_atomic(op)

def rwg_set_carrier(channel: Channel, carrier_freq: float) -> Morphism:
    """Creates an RWG carrier frequency setting morphism (atomic operation).""" 
    op = AtomicMorphism(
        channel=channel,
        start_state=RWGUninitialized(),
        end_state=RWGReady(carrier_freq=carrier_freq),
        duration_cycles=0,  # Instantaneous operation, handled during global sync
        operation_type=OperationType.RWG_SET_CARRIER,
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

    # Create RWGActive state with pending waveforms to load
    if isinstance(start_state, RWGReady):
        end_state = RWGActive(
            carrier_freq=start_state.carrier_freq,
            rf_on=False,
            snapshot=(),
            pending_waveforms=tuple(params)
        )
    else:  # RWGActive
        end_state = RWGActive(
            carrier_freq=start_state.carrier_freq,
            rf_on=start_state.rf_on,
            snapshot=start_state.snapshot,
            pending_waveforms=tuple(params)
        )

    op = AtomicMorphism(
        channel=channel,
        start_state=start_state,
        end_state=end_state,
        duration_cycles=0,
        operation_type=OperationType.RWG_LOAD_COEFFS,
    )
    return from_atomic(op)

def rwg_update_params(
    channel: Channel,
    duration: float,
    start_state: Union[RWGReady, RWGActive],
    end_state: Union[RWGReady, RWGActive]
) -> Morphism:
    """Creates a morphism to trigger an RWG parameter update (a ramp).

    Args:
        channel: RWG channel to operate on
        duration: Duration of the waveform playback in seconds (SI unit)
        start_state: RWG state at the beginning of playback
        end_state: RWG state at the end of playback
    """
    duration_cycles = time_to_cycles(duration)
    op = AtomicMorphism(
        channel=channel,
        start_state=start_state,
        end_state=end_state,
        duration_cycles=duration_cycles,
        operation_type=OperationType.RWG_UPDATE_PARAMS,
    )
    return from_atomic(op)