from abc import ABC, abstractmethod
from typing import Self
from catseq.model import State, HardwareInterface, ResourceIdentifier


class BaseHardware(ABC, HardwareInterface, ResourceIdentifier):
    """
    An abstract base class for all hardware device implementation.

    This class serves as a bridge between the abstract protocols defined in `catseq.model` and
    the concrete hardware device classes. It provides a common implementation for the `ResourceIdentifier`
    protocol and enforces the implementation of the `HardwareInterface` protocol.

    All concrete hardware classes (e.g. `RWGDevice`, `DACDevice`) should inherit from this class.
    """
    def __init__(self, name:str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name
    
    @property
    def instance(self) -> Self:
        return self
    
    @abstractmethod
    def validate_transition(self, from_state: State, to_state: State) -> None:
        """
        Validates if a transition from a given state to another is physically possible 
        and allowed by the hardware.

        This method MUST be implemented by each concrete hardware subclass to
        enforce its specific physical constraits and rules. When a transition
        is invalid, it should raise an exception (e.g., TypeError or a custom exception).

        Args:
            from_state: The starting stage of the transition.
            to_state: The target state of the transition.

        Raises:
            TypeError: If the transition is invalid.
        """
        raise NotImplementedError
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.name}>"