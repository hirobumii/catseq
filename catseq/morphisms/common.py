from catseq.model import State, IdentityMorphism, ChannelT


def Hold(
        channel: ChannelT,
        current_state: State,
        duration: float
) -> IdentityMorphism[ChannelT]:
    """
    Creates an Identity Morphism that holds the current state for a specified duration.
    """
    if duration <= 0:
        raise ValueError("Hold duration must be a positive number.")
    
    return IdentityMorphism(
        name=f"Hold({channel.name}, {duration:.2e}s)",
        dom=((channel, current_state),),
        cod=((channel, current_state),),
        duration=duration
    )

def Marker(channel: ChannelT, current_state: State, label: str) -> IdentityMorphism[ChannelT]:
    """Creates a zero-duration Identity Morphism to act as a marker."""
    return IdentityMorphism(
        name=f"Marker({label})",
        dom=((channel, current_state),),
        cod=((channel, current_state),),
        duration=0.0
    )

def WaitOnTrigger():
    raise NotImplementedError

def Call():
    raise NotImplementedError
