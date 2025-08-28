"""
Common morphism factory functions
"""

from catseq.core.protocols import Channel, State
from catseq.core.objects import SystemState
from catseq.core.morphisms import Morphism, AtomicOperation


def hold(channel: Channel, state: State, duration: float) -> Morphism:
    """
    Creates a morphism that holds a channel in a given state for a duration.

    Args:
        channel: The channel to hold.
        state: The state to hold the channel in.
        duration: The duration of the hold in seconds.

    Returns:
        A Morphism representing the hold operation.
    """
    if duration <= 0:
        raise ValueError("Hold duration must be a positive number.")

    # A hold is a single atomic operation that doesn't change the state.
    hold_op = AtomicOperation(
        channel=channel,
        from_state=state,
        to_state=state,
        duration=duration,
        hardware_params={}
    )

    # The domain and codomain are the same for a hold operation.
    system_state = SystemState({channel: state})

    return Morphism(
        dom=system_state,
        cod=system_state,
        duration=duration,
        lanes={channel: [hold_op]}
    )
