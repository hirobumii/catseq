"""
Common hardware operations shared across different device types.

This module provides universal operations that work with any channel type,
such as hold/wait operations.
"""

from ..debug import factory_breadcrumb
from ..types.common import AtomicMorphism, Channel, OperationType, State, TimingKind
from ..morphism import Morphism, MorphismDef
from ..time_utils import us_to_cycles, time_to_cycles
from ..lanes import Lane


def hold(duration: float) -> MorphismDef:
    """Creates a definition for a hold (wait) operation.

    This is a universal hold function that works with any channel type.

    Args:
        duration: Duration of the hold operation in seconds (SI unit)

    Returns:
        MorphismDef that generates a hold operation for any channel
    """

    def generator(channel: Channel, start_state: State) -> Morphism:
        duration_cycles = time_to_cycles(duration)
        
        # Create identity operation for the specific channel
        identity_op = AtomicMorphism(
            channel=channel,
            start_state=start_state,
            end_state=start_state,
            duration_cycles=duration_cycles,
            operation_type=OperationType.IDENTITY,
            timing_kind=TimingKind.DELAY,
            debug_trace=(factory_breadcrumb(stacklevel=1),),
        )
        
        return Morphism({channel: Lane((identity_op,))})

    return MorphismDef(generator)
