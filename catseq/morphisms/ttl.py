from catseq.model import State, PrimitiveMorphism, LaneMorphism, ChannelT
from catseq.states.common import Uninitialized
from catseq.states.ttl import TTLState, TTLOutputOn, TTLOutputOff
from catseq.morphisms.common import Hold

# Duration of a single RTMQ clock cycle (1 / 250 MHz).
SINGLE_CYCLE_DURATION_S = 4e-9

def initialize(channel: ChannelT) -> PrimitiveMorphism[ChannelT]:
    """Creates a PrimitiveMorphism to initialize a TTL channel."""
    from_state = Uninitialized()
    to_state = TTLOutputOff()

    return PrimitiveMorphism(
        name=f"{channel.name}.Initialize()",
        dom=((channel, from_state),),
        cod=((channel, to_state),),
        duration=SINGLE_CYCLE_DURATION_S
    )

def turn_on(channel: ChannelT, from_state: TTLState) -> PrimitiveMorphism[ChannelT]:
    """Creates a PrimitiveMorphism to turn on a TTL channel's output."""
    if not isinstance(from_state, TTLState):
        raise TypeError(f"from_state for turn_on must be a TTLState, not {type(from_state).__name__}")

    to_state = TTLOutputOn()
    return PrimitiveMorphism(
        name=f"{channel.name}.TurnOn()",
        dom=((channel, from_state),),
        cod=((channel, to_state),),
        duration=SINGLE_CYCLE_DURATION_S
    )

def turn_off(channel: ChannelT, from_state: TTLState) -> PrimitiveMorphism[ChannelT]:
    """Creates a PrimitiveMorphism to turn off a TTL channel's output."""
    if not isinstance(from_state, TTLState):
        raise TypeError(f"from_state for turn_off must be a TTLState, not {type(from_state).__name__}")

    to_state = TTLOutputOff()
    return PrimitiveMorphism(
        name=f"{channel.name}.TurnOff()",
        dom=((channel, from_state),),
        cod=((channel, to_state),),
        duration=SINGLE_CYCLE_DURATION_S
    )

def pulse(channel: ChannelT, from_state: TTLState, duration: float) -> LaneMorphism[ChannelT]:
    """
    Creates a composite LaneMorphism for a TTL pulse.
    The `duration` parameter specifies the time the signal is held high.
    """
    if duration <= 0:
        raise ValueError("Pulse hold duration must be a positive number.")

    m_on = turn_on(channel, from_state)

    # The new state after turning on is the codomain state of m_on
    on_state = m_on.cod[0][1]
    m_hold = Hold(channel, on_state, duration)

    # The new state after holding is the codomain state of m_hold
    off_from_state = m_hold.cod[0][1]
    m_off = turn_off(channel, off_from_state)

    return m_on @ m_hold @ m_off
