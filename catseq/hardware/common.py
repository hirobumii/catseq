"""
Common hardware operations shared across different device types.

This module provides universal operations that work with any channel type,
such as hold/wait operations.
"""

from ..types.common import Channel, State, AtomicMorphism, OperationType
from ..morphism import Morphism, MorphismDef
from ..time_utils import us_to_cycles
from ..lanes import Lane


def hold(duration_us: float) -> MorphismDef:
    """Creates a definition for a hold (wait) operation.
    
    This is a universal hold function that works with any channel type.
    
    Args:
        duration_us: Duration of the hold operation in microseconds
        
    Returns:
        MorphismDef that generates a hold operation for any channel
    """
    
    def generator(channel: Channel, start_state: State) -> Morphism:
        duration_cycles = us_to_cycles(duration_us)
        
        # Create identity operation for the specific channel
        identity_op = AtomicMorphism(
            channel=channel,
            start_state=start_state,
            end_state=start_state,
            duration_cycles=duration_cycles,
            operation_type=OperationType.IDENTITY
        )
        
        return Morphism({channel: Lane((identity_op,))})

    return MorphismDef(generator)