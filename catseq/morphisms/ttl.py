from catseq.protocols import State, Channel
from catseq.model import PrimitiveMorphism, LaneMorphism
from catseq.states.common import Uninitialized
from catseq.states.ttl import TTLState, TTLOutputOn, TTLOutputOff
from catseq.builder import MorphismBuilder
from catseq.morphisms.common import hold

# Duration of a single RTMQ clock cycle (1 / 250 MHz).
SINGLE_CYCLE_DURATION_S = 4e-9


def initialize() -> MorphismBuilder:
    """Creates a deferred morphism to initialize a TTL channel."""

    def generator(channel: Channel, from_state: State) -> LaneMorphism:
        if not isinstance(from_state, Uninitialized):
            raise TypeError(
                f"Cannot initialize a channel that is not in the Uninitialized state. Current state: {from_state}"
            )
        to_state = TTLOutputOff()
        m = PrimitiveMorphism(
            name=f"{channel.name}.init()",
            dom=((channel, from_state),),
            cod=((channel, to_state),),
            duration=SINGLE_CYCLE_DURATION_S,
        )
        return LaneMorphism.from_primitive(m)

    return MorphismBuilder(
        single_generator=generator, default_from_state=Uninitialized()
    )


def turn_on() -> MorphismBuilder:
    """Creates a deferred morphism to turn on a TTL channel's output."""

    def generator(channel: Channel, from_state: State) -> LaneMorphism:
        if not isinstance(from_state, TTLState):
            raise TypeError(
                f"from_state for turn_on must be a TTLState, not {type(from_state).__name__}"
            )
        if isinstance(from_state, TTLOutputOn):
            raise ValueError("Cannot turn_on a channel that is already On.")

        to_state = TTLOutputOn()
        m = PrimitiveMorphism(
            name=f"{channel.name}.on()",
            dom=((channel, from_state),),
            cod=((channel, to_state),),
            duration=SINGLE_CYCLE_DURATION_S,
        )
        return LaneMorphism.from_primitive(m)

    return MorphismBuilder(
        single_generator=generator, default_from_state=TTLOutputOff()
    )


def turn_off() -> MorphismBuilder:
    """Creates a deferred morphism to turn off a TTL channel's output."""

    def generator(channel: Channel, from_state: State) -> LaneMorphism:
        if not isinstance(from_state, TTLState):
            raise TypeError(
                f"from_state for turn_off must be a TTLState, not {type(from_state).__name__}"
            )
        if isinstance(from_state, TTLOutputOff):
            raise ValueError("Cannot turn_off a channel that is already Off.")

        to_state = TTLOutputOff()
        m = PrimitiveMorphism(
            name=f"{channel.name}.off()",
            dom=((channel, from_state),),
            cod=((channel, to_state),),
            duration=SINGLE_CYCLE_DURATION_S,
        )
        return LaneMorphism.from_primitive(m)

    return MorphismBuilder(single_generator=generator, default_from_state=TTLOutputOn())


def pulse(duration: float) -> MorphismBuilder:
    """
    Creates a deferred composite morphism for a TTL pulse.
    """
    if duration <= 0:
        raise ValueError("Pulse hold duration must be a positive number.")

    # Compose the builder objects. The actual chaining of states happens
    # inside the builder's __matmul__ method at execution time.
    return turn_on() @ hold(duration) @ turn_off()
