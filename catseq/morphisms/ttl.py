"""
TTL morphism factory functions
"""

from catseq.core.protocols import Channel
from catseq.core.objects import SystemState
from catseq.core.morphisms import Morphism, AtomicOperation
from catseq.states.ttl import TTLOn, TTLOff
from catseq.states.common import Uninitialized
from catseq.hardware.ttl import TTLDevice


def pulse(channel: Channel, duration: float) -> Morphism:
    """
    Create a TTL pulse morphism: OFF -> ON -> OFF.
    The state transitions are instantaneous (zero-duration).

    Args:
        channel: TTL channel to pulse.
        duration: Duration of the high pulse in seconds.

    Returns:
        Morphism representing the complete pulse sequence.
    """
    if duration <= 0:
        raise ValueError("Pulse duration must be positive.")

    if not isinstance(channel.device, TTLDevice):
        raise TypeError(f"Channel {channel.name} must use TTLDevice.")

    off_state = TTLOff()
    on_state = TTLOn()

    # The domain and codomain both assume the channel is OFF before and after.
    dom = SystemState({channel: off_state})
    cod = SystemState({channel: off_state})

    # State transitions are instantaneous at the morphism level.
    turn_on_op = AtomicOperation(
        channel=channel,
        from_state=off_state,
        to_state=on_state,
        duration=0.0,
        hardware_params={}
    )

    hold_on_op = AtomicOperation(
        channel=channel,
        from_state=on_state,
        to_state=on_state,
        duration=duration,
        hardware_params={}
    )

    turn_off_op = AtomicOperation(
        channel=channel,
        from_state=on_state,
        to_state=off_state,
        duration=0.0,
        hardware_params={}
    )

    # The total duration of the morphism is the duration of the pulse itself.
    return Morphism(
        dom=dom,
        cod=cod,
        duration=duration,
        lanes={channel: [turn_on_op, hold_on_op, turn_off_op]}
    )


def initialize(channel: Channel, initial_state: TTLOff = TTLOff()) -> Morphism:
    """
    Initialize a TTL channel from Uninitialized to a known state (default OFF).

    Args:
        channel: TTL channel to initialize.
        initial_state: The target state, must be TTLOff or TTLOn.

    Returns:
        A Morphism representing the initialization.
    """
    if not isinstance(channel.device, TTLDevice):
        raise TypeError(f"Channel {channel.name} must use TTLDevice.")

    if not isinstance(initial_state, (TTLOn, TTLOff)):
        raise TypeError(f"Initial state must be TTLOn or TTLOff, not {type(initial_state).__name__}")

    uninit_state = Uninitialized()

    dom = SystemState({channel: uninit_state})
    cod = SystemState({channel: initial_state})

    # Initialization is an instantaneous operation.
    init_op = AtomicOperation(
        channel=channel,
        from_state=uninit_state,
        to_state=initial_state,
        duration=0.0,
        hardware_params={}
    )

    return Morphism(
        dom=dom,
        cod=cod,
        duration=0.0,
        lanes={channel: [init_op]}
    )