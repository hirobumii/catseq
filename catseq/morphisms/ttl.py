"""
TTL morphism factory functions

Provides convenient functions for creating TTL channel morphisms:
- pulse(): Create TTL pulse sequences
- hold_on(): Hold TTL channel in ON state
- hold_off(): Hold TTL channel in OFF state
"""

from catseq.core.protocols import Channel
from catseq.core.objects import SystemState
from catseq.core.morphisms import Morphism, AtomicOperation
from catseq.states import TTLOn, TTLOff, TTLInput, Uninitialized
from catseq.hardware import TTLDevice

# Duration of a single RTMQ clock cycle (1 / 250 MHz)
SINGLE_CYCLE_DURATION_S = 4e-9


def pulse(channel: Channel, duration: float) -> Morphism:
    """
    Create a TTL pulse morphism: OFF -> ON -> OFF
    
    Args:
        channel: TTL channel to pulse
        duration: Duration of the high pulse in seconds
        
    Returns:
        Morphism representing the complete pulse sequence
    """
    if duration <= 0:
        raise ValueError("Pulse duration must be positive")
    
    if not isinstance(channel.device, TTLDevice):
        raise TypeError(f"Channel {channel.name} must use TTLDevice")
    
    # States for the pulse sequence
    off_state = TTLOff()
    on_state = TTLOn()
    
    # System states
    dom = SystemState({channel: off_state})
    cod = SystemState({channel: off_state})  # Returns to OFF after pulse
    
    # Create atomic operations for the pulse
    turn_on_op = AtomicOperation(
        channel=channel,
        from_state=off_state,
        to_state=on_state,
        duration=SINGLE_CYCLE_DURATION_S,
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
        duration=SINGLE_CYCLE_DURATION_S,
        hardware_params={}
    )
    
    total_duration = 2 * SINGLE_CYCLE_DURATION_S + duration
    
    return Morphism(
        dom=dom,
        cod=cod,
        duration=total_duration,
        lanes={channel: [turn_on_op, hold_on_op, turn_off_op]}
    )


def hold_on(channel: Channel, duration: float) -> Morphism:
    """
    Hold TTL channel in ON state for specified duration
    
    Args:
        channel: TTL channel 
        duration: Hold duration in seconds
        
    Returns:
        Morphism: ON -> ON
    """
    if duration <= 0:
        raise ValueError("Hold duration must be positive")
    
    if not isinstance(channel.device, TTLDevice):
        raise TypeError(f"Channel {channel.name} must use TTLDevice")
    
    on_state = TTLOn()
    dom = SystemState({channel: on_state})
    cod = SystemState({channel: on_state})
    
    hold_op = AtomicOperation(
        channel=channel,
        from_state=on_state,
        to_state=on_state,
        duration=duration,
        hardware_params={}
    )
    
    return Morphism(
        dom=dom,
        cod=cod,
        duration=duration,
        lanes={channel: [hold_op]}
    )


def hold_off(channel: Channel, duration: float) -> Morphism:
    """
    Hold TTL channel in OFF state for specified duration
    
    Args:
        channel: TTL channel
        duration: Hold duration in seconds
        
    Returns:
        Morphism: OFF -> OFF  
    """
    if duration <= 0:
        raise ValueError("Hold duration must be positive")
    
    if not isinstance(channel.device, TTLDevice):
        raise TypeError(f"Channel {channel.name} must use TTLDevice")
    
    off_state = TTLOff()
    dom = SystemState({channel: off_state})
    cod = SystemState({channel: off_state})
    
    hold_op = AtomicOperation(
        channel=channel,
        from_state=off_state,
        to_state=off_state,
        duration=duration,
        hardware_params={}
    )
    
    return Morphism(
        dom=dom,
        cod=cod,
        duration=duration,
        lanes={channel: [hold_op]}
    )


def initialize(channel: Channel) -> Morphism:
    """
    Initialize TTL channel from Uninitialized to OFF state
    
    Args:
        channel: TTL channel to initialize
        
    Returns:
        Morphism: Uninitialized -> OFF
    """
    if not isinstance(channel.device, TTLDevice):
        raise TypeError(f"Channel {channel.name} must use TTLDevice")
    
    uninit_state = Uninitialized()
    off_state = TTLOff()
    
    dom = SystemState({channel: uninit_state})
    cod = SystemState({channel: off_state})
    
    init_op = AtomicOperation(
        channel=channel,
        from_state=uninit_state,
        to_state=off_state,
        duration=SINGLE_CYCLE_DURATION_S,
        hardware_params={}
    )
    
    return Morphism(
        dom=dom,
        cod=cod,
        duration=SINGLE_CYCLE_DURATION_S,
        lanes={channel: [init_op]}
    )