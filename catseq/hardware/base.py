from abc import ABC, abstractmethod
from typing import Tuple, Optional
from catseq.core.protocols import State, HardwareDevice


class BaseHardware(ABC, HardwareDevice):
    """
    Base hardware device class providing common validation functionality
    
    Implements the HardwareDevice protocol from the core system
    """

    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @abstractmethod
    def validate_transition(self, from_state: State, to_state: State) -> None:
        """
        Validates if a state transition is physically possible
        
        Raises PhysicsViolationError if transition is invalid
        """
        pass

    def validate_taylor_coefficients(
        self, 
        freq_coeffs: Tuple[Optional[float], ...], 
        amp_coeffs: Tuple[Optional[float], ...]
    ) -> None:
        """
        Validates Taylor coefficients for hardware feasibility
        
        Default implementation allows any coefficients.
        Subclasses should override for specific hardware constraints.
        """
        pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.name}>"
