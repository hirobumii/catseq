"""
AtomicMorphism factories.

This module provides factory functions for creating AtomicMorphism objects,
which are the fundamental building blocks of sequences.
"""
from typing import List, Union, Callable, Dict, Tuple

from .debug import factory_breadcrumb
from .morphism import Morphism, from_atomic, Lane
from .types.common import (
    Board,
    Channel, 
    OperationType, 
    AtomicMorphism, 
    State,
    TimedRegion,
    TimingKind,
)
from .types.ttl import TTLState
from .types.rwg import (
    RWGActive,
    RWGReady,
    RWGUninitialized,
    WaveformParams,
)
from .types.rsp import (
    RSPPIDActive,
    RSPPIDReady,
    RSPPIDConfig,
    RSPReady,
    RSPUninitialized,
    RSPState,
    RSPWaveformParams,
)

def ttl_init(channel: Channel, initial_state: TTLState = TTLState.OFF) -> Morphism:
    """Creates a TTL initialization morphism."""
    op = AtomicMorphism(
        channel=channel,
        start_state=None,
        end_state=initial_state,
        duration_cycles=0,
        operation_type=OperationType.TTL_INIT,
        timing_kind=TimingKind.EXACT_EVENT,
        debug_trace=(factory_breadcrumb(stacklevel=1),),
    )
    return from_atomic(op)

def ttl_on(channel: Channel, start_state: State = TTLState.OFF) -> Morphism:
    """Creates a TTL ON morphism."""
    op = AtomicMorphism(
        channel=channel,
        start_state=start_state,
        end_state=TTLState.ON,
        duration_cycles=0,
        operation_type=OperationType.TTL_ON,
        timing_kind=TimingKind.EXACT_EVENT,
        debug_trace=(factory_breadcrumb(stacklevel=1),),
    )
    return from_atomic(op)

def ttl_off(channel: Channel, start_state: State = TTLState.ON) -> Morphism:
    """Creates a TTL OFF morphism."""
    op = AtomicMorphism(
        channel=channel,
        start_state=start_state,
        end_state=TTLState.OFF,
        duration_cycles=0,
        operation_type=OperationType.TTL_OFF,
        timing_kind=TimingKind.EXACT_EVENT,
        debug_trace=(factory_breadcrumb(stacklevel=1),),
    )
    return from_atomic(op)

def rwg_board_init(channel: Channel) -> Morphism:
    """Creates an RWG board-level initialization morphism (atomic operation)."""
    op = AtomicMorphism(
        channel=channel,
        start_state=RWGUninitialized(),
        end_state=RWGUninitialized(),  # Still uninitialized until carrier is set
        duration_cycles=0,
        operation_type=OperationType.RWG_INIT,
        timing_kind=TimingKind.EXACT_EVENT,
        debug_trace=(factory_breadcrumb(stacklevel=1),),
    )
    return from_atomic(op)

def rwg_set_carrier(channel: Channel, carrier_freq: float) -> Morphism:
    """Creates an RWG carrier frequency setting morphism (atomic operation).""" 
    op = AtomicMorphism(
        channel=channel,
        start_state=RWGUninitialized(),
        end_state=RWGReady(carrier_freq=carrier_freq),
        duration_cycles=0,
        operation_type=OperationType.RWG_SET_CARRIER,
        timing_kind=TimingKind.EXACT_EVENT,
        debug_trace=(factory_breadcrumb(stacklevel=1),),
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
        timing_kind=TimingKind.EXACT_EVENT,
        debug_trace=(factory_breadcrumb(stacklevel=1),),
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
        timing_kind=TimingKind.EXACT_EVENT,
        debug_trace=(factory_breadcrumb(stacklevel=1),),
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
    """Creates a multi-channel, potentially multi-board opaque timed region morphism.

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

        op = TimedRegion(
            channel=channel,
            start_state=start_state,
            end_state=end_state,
            duration_cycles=duration_cycles,
            board_funcs=board_funcs,
            operation_type=OperationType.OPAQUE_OASM_FUNC,
            timing_kind=TimingKind.TIMED_REGION,
            debug_trace=(factory_breadcrumb(stacklevel=1),),
            user_func=board_func,
            user_args=user_args,
            user_kwargs=user_kwargs,
            metadata=metadata,
        )
        lanes[channel] = Lane((op,))

    return Morphism(lanes)

def rsp_board_init(channel: Channel) -> Morphism:
    """Creates an RSP board-level initialization morphism."""
    op = AtomicMorphism(
        channel=channel,
        start_state=RSPUninitialized(),
        end_state=RSPUninitialized(),
        duration_cycles=0, # 256 expected
        operation_type=OperationType.RSP_INIT,
        timing_kind=TimingKind.EXACT_EVENT,
        debug_trace=(factory_breadcrumb(stacklevel=1),),
    )
    return from_atomic(op)


def rsp_set_carrier(channel: Channel, carrier_freq: float) -> Morphism:
    """Creates an RSP carrier-frequency setup morphism for one RF output."""
    op = AtomicMorphism(
        channel=channel,
        start_state=RSPUninitialized(),
        end_state=RSPReady(carrier_freq),
        duration_cycles=0, # 737 expected
        operation_type=OperationType.RSP_SET_CARRIER,
        timing_kind=TimingKind.EXACT_EVENT,
        debug_trace=(factory_breadcrumb(stacklevel=1),),
    )
    return from_atomic(op)


def rsp_pid_config(channel: Channel, config: RSPPIDConfig, start_state: RSPState) -> Morphism:
    """Creates an RSP PID-loop configuration morphism."""
    if not isinstance(start_state, (RSPReady, RSPPIDReady, RSPPIDActive)):
        raise TypeError(
            "RSP pid_config must start from RSPReady/RSPPIDReady/RSPPIDActive, "
            f"not {type(start_state)}"
        )
    op = AtomicMorphism(
        channel=channel,
        start_state=start_state,
        end_state=RSPPIDReady(start_state.carrier_freq, config),
        duration_cycles=0, # 39
        operation_type=OperationType.RSP_PID_CONFIG,
        timing_kind=TimingKind.EXACT_EVENT,
        debug_trace=(factory_breadcrumb(stacklevel=1),),
    )
    return from_atomic(op)


def rsp_pid_start(channel: Channel, start_state: RSPPIDReady | RSPPIDActive) -> Morphism:
    """Starts or resumes an already configured RSP PID loop."""
    if not isinstance(start_state, (RSPPIDReady, RSPPIDActive)):
        raise TypeError(
            f"RSP pid_start must start from RSPPIDReady/RSPPIDActive, not {type(start_state)}"
        )
    op = AtomicMorphism(
        channel=channel,
        start_state=start_state,
        end_state=RSPPIDActive(start_state.carrier_freq, start_state.config, hold=False),
        duration_cycles=0, # 3
        operation_type=OperationType.RSP_PID_START,
        timing_kind=TimingKind.EXACT_EVENT,
        debug_trace=(factory_breadcrumb(stacklevel=1),),
    )
    return from_atomic(op)


def rsp_pid_hold(channel: Channel, start_state: RSPPIDActive) -> Morphism:
    """Holds an active RSP PID loop by deasserting its DGT valid source."""
    if not isinstance(start_state, RSPPIDActive):
        raise TypeError(f"RSP pid_hold must start from RSPPIDActive, not {type(start_state)}")
    op = AtomicMorphism(
        channel=channel,
        start_state=start_state,
        end_state=RSPPIDActive(start_state.carrier_freq, start_state.config, hold=True),
        duration_cycles=0, #2
        operation_type=OperationType.RSP_PID_HOLD,
        timing_kind=TimingKind.EXACT_EVENT,
        debug_trace=(factory_breadcrumb(stacklevel=1),),
    )
    return from_atomic(op)


def rsp_pid_release(channel: Channel, start_state: RSPPIDActive) -> Morphism:
    """Releases a held RSP PID loop, allowing it to update again."""
    if not isinstance(start_state, RSPPIDActive):
        raise TypeError(f"RSP pid_release must start from RSPPIDActive, not {type(start_state)}")
    op = AtomicMorphism(
        channel=channel,
        start_state=start_state,
        end_state=RSPPIDActive(start_state.carrier_freq, start_state.config, hold=False),
        duration_cycles=0, #15
        operation_type=OperationType.RSP_PID_RELEASE,
        timing_kind=TimingKind.EXACT_EVENT,
        debug_trace=(factory_breadcrumb(stacklevel=1),),
    )
    return from_atomic(op)

def rsp_pid_relink(channel: Channel, start_state: RSPPIDActive) -> Morphism:
    """Reconnects a held RSP PID loop, restoring the ACU→MUA→RFG signal chain."""
    if not isinstance(start_state, RSPPIDActive):
        raise TypeError(f"RSP pid_relink must start from RSPPIDActive, not {type(start_state)}")
    op = AtomicMorphism(
        channel=channel,
        start_state=start_state,
        end_state=RSPPIDActive(start_state.carrier_freq, start_state.config, hold=False),
        duration_cycles=0,  # 15 expected
        operation_type=OperationType.RSP_PID_RELINK,
        timing_kind=TimingKind.EXACT_EVENT,
        debug_trace=(factory_breadcrumb(stacklevel=1),),
    )
    return from_atomic(op)


def rsp_rf_config(channel: Channel, config: RSPWaveformParams, start_state: RSPReady) -> Morphism:
    """Sets one RSP RF output to a static configured value."""
    if not isinstance(start_state, (RSPReady, RSPPIDReady, RSPPIDActive)):
        raise TypeError(f"RSP rf_config must start from RSPReady, not {type(start_state)}")
    if channel.local_id != config.rf_out:
        raise TypeError(
            f"RF configuration mismatch: expected RF channel rf{channel.local_id}, "
            f"but got channel rf{config.rf_out}."
        )
    op = AtomicMorphism(
        channel=channel,
        start_state=start_state,
        end_state=RSPReady(carrier_freq=start_state.carrier_freq, static_rf=config),
        duration_cycles=0,  # 13 expected
        operation_type=OperationType.RSP_RF_CONFIG,
        timing_kind=TimingKind.EXACT_EVENT,
        debug_trace=(factory_breadcrumb(stacklevel=1),),
    )
    return from_atomic(op)