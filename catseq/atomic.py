"""
AtomicMorphism factories.

This module provides factory functions for creating AtomicMorphism objects,
which are the fundamental building blocks of sequences.
"""
from typing import List, Union, Callable, Dict, Tuple

from .morphism import Morphism, from_atomic, Lane
from .time_utils import time_to_cycles
from .types.common import (
    Board,
    Channel, 
    OperationType, 
    AtomicMorphism, 
    State,
    BlackBoxAtomicMorphism
)
from .types.ttl import TTLState
from .types.rwg import (
    RWGActive,
    RWGReady,
    RWGUninitialized,
    WaveformParams,
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
        duration_cycles=1,  # All atomic operations use 1 cycle for stable compiler ordering
        operation_type=OperationType.RWG_INIT,
    )
    return from_atomic(op)

def rwg_set_carrier(channel: Channel, carrier_freq: float) -> Morphism:
    """Creates an RWG carrier frequency setting morphism (atomic operation).""" 
    op = AtomicMorphism(
        channel=channel,
        start_state=RWGUninitialized(),
        end_state=RWGReady(carrier_freq=carrier_freq),
        duration_cycles=1,  # All atomic operations use 1 cycle for stable compiler ordering
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
        duration_cycles=1,  # All atomic operations use 1 cycle for stable compiler ordering
        operation_type=OperationType.RWG_LOAD_COEFFS,
    )
    return from_atomic(op)

def rwg_update_params(
    channel: Channel,
    start_state: Union[RWGReady, RWGActive],
    end_state: Union[RWGReady, RWGActive]
) -> Morphism:
    """Creates a morphism to trigger an RWG parameter update (atomic operation).

    Args:
        channel: RWG channel to operate on
        start_state: RWG state at the beginning of playback
        end_state: RWG state at the end of playback
    """
    op = AtomicMorphism(
        channel=channel,
        start_state=start_state,
        end_state=end_state,
        duration_cycles=0,  
        operation_type=OperationType.RWG_UPDATE_PARAMS,
    )
    return from_atomic(op)

def oasm_black_box(
    channel_states: Dict[Channel, Tuple[State, State]],
    duration_cycles: int,
    board_funcs: Dict[Board, Callable],
    user_args: tuple = (),
    user_kwargs: dict = {},
    metadata: dict | None = None,
) -> Morphism:
    """Creates a multi-channel, potentially multi-board black-box Morphism.

    This factory creates a single Morphism that contains multiple BlackBoxAtomicMorphisms,
    one for each specified channel. It looks up the correct user-defined function
    from the board_funcs dictionary based on the channel's board.

    Args:
        channel_states: A dictionary mapping each channel to a tuple of its
                        (start_state, end_state) for this black box.
        duration_cycles: The fixed duration of the black-box operation in cycles.
        board_funcs: A dictionary mapping each Board to the user-defined function
                     to be executed on that board.
        user_args: Positional arguments to pass to the user_func.
        user_kwargs: Keyword arguments to pass to the user_func.
        metadata: Additional metadata for the black box (e.g., loop information).

    Returns:
        A Morphism object representing the multi-channel black box.
    """
    lanes = {}
    if not channel_states:
        raise ValueError("channel_states cannot be empty for a black-box operation.")

    # Validate that all channels belong to a board specified in board_funcs
    for channel in channel_states.keys():
        if channel.board not in board_funcs:
            raise ValueError(
                f"Channel {channel} belongs to board {channel.board.id}, but no function "
                f"was provided for this board in board_funcs."
            )

    # Handle metadata default value
    if metadata is None:
        metadata = {}

    for channel, (start_state, end_state) in channel_states.items():
        # Look up the correct function for this channel's board
        board_func = board_funcs[channel.board]

        op = BlackBoxAtomicMorphism(
            channel=channel,
            start_state=start_state,
            end_state=end_state,
            duration_cycles=duration_cycles,
            operation_type=OperationType.OPAQUE_OASM_FUNC,
            user_func=board_func,
            user_args=user_args,
            user_kwargs=user_kwargs,
            metadata=metadata,
        )
        lanes[channel] = Lane((op,))

    return Morphism(lanes)
