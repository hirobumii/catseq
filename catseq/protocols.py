from __future__ import annotations
from typing import Protocol, Type
from dataclasses import dataclass

# This file contains the core abstract protocols and base classes for the catseq model.
# It has no internal imports from the catseq package, allowing other modules
# to import from it without creating circular dependencies.

@dataclass(frozen=True)
class State:
    """Base class for all hardware state representations."""
    pass

class Dynamics(Protocol):
    """A marker protocol for any object intended as a Morphism's dynamics."""
    pass

class HardwareInterface(Protocol):
    """A protocol that concrete hardware classes must implement for validation."""
    def __init__(self, name: str) -> None: ...
    def validate_transition(self, from_state: State, to_state: State) -> None: ...

class ResourceIdentifier(Protocol):
    """A protocol that all Channel classes must conform to."""
    @property
    def name(self) -> str: ...
    
    @property
    def instance(self) -> HardwareInterface: ...

class Channel(ResourceIdentifier):
    """
    The concrete base class for all hardware channel identifiers.
    This class explicitly implements the ResourceIdentifier protocol.
    """
    _instances = {}

    def __new__(cls, name: str, hardware_type: Type[HardwareInterface]):
        if not isinstance(name, str):
            raise TypeError("Channel name must be a string.")

        # Implements a singleton pattern based on the channel name.
        if name in cls._instances:
            return cls._instances[name]
        
        instance = super().__new__(cls)
        cls._instances[name] = instance
        return instance

    def __init__(self, name: str, hardware_type: Type[HardwareInterface]):
        # The __init__ can be called multiple times on a singleton,
        # so we check if initialization has already been done.
        if hasattr(self, '_name'):
            return
        self._name = name
        self._hardware_instance = hardware_type(name=name)

    @property
    def name(self) -> str:
        return self._name

    @property
    def instance(self) -> HardwareInterface:
        return self._hardware_instance

    def __repr__(self) -> str:
        return f"<Channel: {self.name}>"

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Channel):
            return NotImplemented
        return self.name == other.name
