from catseq.core.protocols import State, PhysicsViolationError
from catseq.hardware.base import BaseHardware
from catseq.states import TTLState, TTLInput, TTLOn, TTLOff, Uninitialized


class TTLDevice(BaseHardware):
    """
    TTL device supporting input/output state transitions
    
    Valid transitions:
    - Uninitialized -> Any TTL state
    - TTLInput <-> TTLOn/TTLOff (configuration change)
    - TTLOn <-> TTLOff (output toggle)
    """

    def validate_transition(self, from_state: State, to_state: State) -> None:
        # Allow any transition from uninitialized state
        if isinstance(from_state, Uninitialized):
            if isinstance(to_state, TTLState):
                return
            else:
                raise PhysicsViolationError(
                    f"TTL device '{self.name}' cannot transition from Uninitialized to {type(to_state).__name__}"
                )
        
        # Both states must be TTL states for other transitions
        if not isinstance(from_state, TTLState) or not isinstance(to_state, TTLState):
            raise PhysicsViolationError(
                f"TTL device '{self.name}' requires TTL states, got {type(from_state).__name__} -> {type(to_state).__name__}"
            )
        
        # All TTL state transitions are physically valid
        # (TTL hardware can always change between input/output modes and high/low states)
        return
