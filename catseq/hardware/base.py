from abc import ABC, abstractmethod
from catseq.protocols import State, HardwareInterface


class BaseHardware(ABC, HardwareInterface):
    """
    An abstract base class for all hardware device implementation.
    It no longer needs to implement ResourceIdentifier, as the Channel class handles that.
    """

    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @abstractmethod
    def validate_transition(self, from_state: State, to_state: State) -> None:
        """
        Validates if a transition from a given state to another is physically possible
        and allowed by the hardware.
        """
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.name}>"
