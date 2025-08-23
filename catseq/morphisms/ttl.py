from catseq.protocols import State, Channel
from catseq.model import PrimitiveMorphism, LaneMorphism
from catseq.states.common import Uninitialized
from catseq.states.ttl import TTLState, TTLOutputOn, TTLOutputOff
from catseq.morphisms.common import Hold

# Duration of a single RTMQ clock cycle (1 / 250 MHz).
SINGLE_CYCLE_DURATION_S = 4e-9

def initialize(channel: Channel) -> PrimitiveMorphism:
    """Creates a PrimitiveMorphism to initialize a TTL channel."""
    from_state = Uninitialized()
    to_state = TTLOutputOff()

    return PrimitiveMorphism(
        name=f"{channel.name}.Initialize()",
        dom=((channel, from_state),),
        cod=((channel, to_state),),
        duration=SINGLE_CYCLE_DURATION_S
    )

def turn_on(channel: Channel, from_state: TTLState = TTLOutputOff()) -> PrimitiveMorphism:
    """Creates a PrimitiveMorphism to turn on a TTL channel's output."""
    if not isinstance(from_state, TTLState):
        raise TypeError(f"from_state for turn_on must be a TTLState, not {type(from_state).__name__}")
    if isinstance(from_state, TTLOutputOn):
        raise ValueError("Cannot turn_on a channel that is already On.")

    to_state = TTLOutputOn()
    return PrimitiveMorphism(
        name=f"{channel.name}.TurnOn()",
        dom=((channel, from_state),),
        cod=((channel, to_state),),
        duration=SINGLE_CYCLE_DURATION_S
    )

def turn_off(channel: Channel, from_state: TTLState = TTLOutputOn()) -> PrimitiveMorphism:
    """Creates a PrimitiveMorphism to turn off a TTL channel's output."""
    if not isinstance(from_state, TTLState):
        raise TypeError(f"from_state for turn_off must be a TTLState, not {type(from_state).__name__}")
    if isinstance(from_state, TTLOutputOff):
        raise ValueError("Cannot turn_off a channel that is already Off.")

    to_state = TTLOutputOff()
    return PrimitiveMorphism(
        name=f"{channel.name}.TurnOff()",
        dom=((channel, from_state),),
        cod=((channel, to_state),),
        duration=SINGLE_CYCLE_DURATION_S
    )

def pulse(channel: Channel, duration: float, from_state: TTLState = TTLOutputOff()) -> LaneMorphism:
    """
    Creates a composite LaneMorphism for a TTL pulse.
    The `duration` parameter specifies the time the signal is held high.
    """
    if duration <= 0:
        raise ValueError("Pulse hold duration must be a positive number.")
    if isinstance(from_state, TTLOutputOn):
        raise ValueError("Cannot pulse a channel that is already On.")

    m_on = turn_on(channel, from_state)
    
    on_state = m_on.cod[0][1]
    if not isinstance(on_state, TTLState):
        raise TypeError(f"Internal logic error: state after turn_on is not a TTLState, but {type(on_state).__name__}")
    m_hold = Hold(channel, on_state, duration)

    off_from_state = m_hold.cod[0][1]
    if not isinstance(off_from_state, TTLState):
        raise TypeError(f"Internal logic error: state before turn_off is not a TTLState, but {type(off_from_state).__name__}")
    m_off = turn_off(channel, off_from_state)

    return m_on @ m_hold @ m_off
