from catseq.model import State, Morphism, ChannelT


def Hold(
        channel: ChannelT,
        current_state: State,
        duration: float
) -> Morphism[ChannelT]:
    """
    Creates an Identity Morphism that holds the current state for a specified duration.

    This is the most fundamental common Morphism, representing a "wait" or
    "delay" operation where the state of the channel does not change. It is
    generic and can be applied to any channel type.

    Args:
        channel: The hardware channel (conforming to the ResourceIdentifier
                 protocol) to which this hold applies.
        current_state: The state that the channel is currently in and will
                       be held in.
        duration: The duration of the hold in the system's base time unit
                  (e.g., microseconds).

    Returns:
        A Morphism object representing the hold operation.
        
    Raises:
        ValueError: If the duration is not a positive number.
    """
    if duration <= 0:
        raise ValueError("Hold duration must be a positive numbers.")
    
    domain_obj = ((channel, current_state),)
    codomain_obj = ((channel, current_state),)

    return Morphism[ChannelT](
        name=f"Hold({channel.name}, {duration:.2f}us)",
        dom=domain_obj,
        cod=codomain_obj,
        duration=duration,
        dynamics=None
    )

def Marker(channel: ChannelT, current_state: State, label: str) -> Morphism[ChannelT]:
    return Morphism[ChannelT](
        name=f"Marker({label})",
        dom=((channel, current_state),),
        cod=((channel, current_state),),
        duration=0.0,
        dynamics=None
    )

def WaitOnTrigger() -> Morphism:
    ...

def Call()-> Morphism:
    ...