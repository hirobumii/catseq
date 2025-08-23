from __future__ import annotations
from catseq.protocols import State, Channel
from catseq.model import IdentityMorphism, LaneMorphism
from catseq.builder import MorphismBuilder


def hold(duration: float) -> MorphismBuilder:
    """
    Creates a deferred hold operation.
    This holds the channel in whatever state it is currently in.
    """
    if duration <= 0:
        raise ValueError("Hold duration must be a positive number.")

    def generator(channel: Channel, from_state: State) -> LaneMorphism:
        m = IdentityMorphism(
            name=f"hold({duration:.2e}s)",
            dom=((channel, from_state),),
            cod=((channel, from_state),),
            duration=duration
        )
        return LaneMorphism.from_primitive(m)

    return MorphismBuilder(single_generator=generator)


def marker(label: str) -> MorphismBuilder:
    """Creates a deferred, zero-duration marker."""
    def generator(channel: Channel, from_state: State) -> LaneMorphism:
        m = IdentityMorphism(
            name=f"marker('{label}')",
            dom=((channel, from_state),),
            cod=((channel, from_state),),
            duration=0.0
        )
        return LaneMorphism.from_primitive(m)

    return MorphismBuilder(single_generator=generator)


def wait_on_trigger():
    raise NotImplementedError

def call():
    raise NotImplementedError
