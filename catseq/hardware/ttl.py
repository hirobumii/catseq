from catseq.protocols import State
from catseq.hardware.base import BaseHardware
from catseq.states.common import Uninitialized
from catseq.states.ttl import TTLState


class TTLDevice(BaseHardware):
    def validate_transition(self, from_state: State, to_state: State) -> None:
        if not isinstance(to_state, TTLState):
            raise TypeError(
                f"Invalid target stage '{type(to_state).__name__}' for TTL device '{self.name}"
            )

        if not isinstance(from_state, (Uninitialized, TTLState)):
            raise TypeError(
                f"Invalid source stage '{type(to_state).__name__}' for TTL device '{self.name}"
            )

        pass
