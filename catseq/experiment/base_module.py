"""Reusable sequence modules and services."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields
from functools import cached_property

from catseq.morphism import Morphism
from catseq.types import Channel, State


def module_field(module_class: type["BaseModule"], default_instance: "BaseModule"):
    """Declare a service dependency with an existing default module instance."""

    if not issubclass(module_class, BaseModule):
        raise TypeError("module_field only accepts BaseModule subclasses")
    return field(default_factory=lambda: default_instance)


def service_field(service_class: type["BaseService"]):
    """Declare a service dependency constructed with its default parameters."""

    if not issubclass(service_class, BaseService):
        raise TypeError("service_field only accepts BaseService subclasses")
    return field(default_factory=service_class)


@dataclass
class BaseModule(ABC):
    """A logical group of sequence parameters and channel configuration."""

    def __post_init__(self) -> None:
        for item in fields(self):
            if isinstance(getattr(self, item.name), BaseModule):
                raise TypeError(
                    f"a module cannot own another module field {item.name!r}"
                )

    @abstractmethod
    def init(self, hard: bool = False) -> Morphism:
        """Build the module initialization sequence."""

    @abstractmethod
    def channel_styles(self) -> dict[Channel, dict]:
        """Return presentation metadata for channels owned by the module."""

    @property
    @abstractmethod
    def default_state(self) -> dict[Channel, State]:
        """Return the module's initial channel states."""


@dataclass
class BaseService(ABC):
    """An experimental capability composed from sequence modules."""

    @property
    @abstractmethod
    def module_list(self) -> list[BaseModule]:
        """Return the modules used by this service."""

    @cached_property
    def default_states(self) -> dict[Channel, State]:
        combined: dict[Channel, State] = {}
        for module in self.module_list:
            combined.update(module.default_state)
        return combined

    @property
    def style(self) -> dict[Channel, dict]:
        combined: dict[Channel, dict] = {}
        for module in self.module_list:
            combined.update(module.channel_styles())
        return combined


__all__ = [
    "BaseModule",
    "BaseService",
    "module_field",
    "service_field",
]
