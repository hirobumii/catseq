from catseq.core.protocols import State, PhysicsViolationError
from catseq.hardware.base import BaseHardware
from catseq.states.common import Uninitialized
from catseq.states.ttl import TTLOn, TTLOff


class TTLDevice(BaseHardware):
    """
    TTL device supporting output state transitions.

    Valid transitions:
    - Uninitialized -> TTLOn or TTLOff
    - TTLOn <-> TTLOff
    """

    def validate_transition(self, from_state: State, to_state: State) -> None:
        # Allow any transition from Uninitialized to a valid TTL output state
        if isinstance(from_state, Uninitialized):
            if isinstance(to_state, (TTLOn, TTLOff)):
                return
            else:
                raise PhysicsViolationError(
                    f"TTL device '{self.name}' can only be initialized to TTLOn or TTLOff, not {type(to_state).__name__}"
                )

        # For other transitions, both states must be TTL output states
        if not isinstance(from_state, (TTLOn, TTLOff)) or not isinstance(to_state, (TTLOn, TTLOff)):
            raise PhysicsViolationError(
                f"TTL device '{self.name}' only supports TTLOn/TTLOff states, "
                f"got {type(from_state).__name__} -> {type(to_state).__name__}"
            )

        # All transitions between TTLOn and TTLOff are valid
        return
