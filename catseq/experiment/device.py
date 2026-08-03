"""Device roles and lifecycle aggregation for experiment control."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields
from typing import Any, Generic, Iterator, TypeVar, cast

from .result import BaseResult


TResult = TypeVar("TResult", bound=BaseResult)


def device_field(device_class: type["BaseDevice"]):
    """Declare one concrete device on a DeviceList."""

    return field(default_factory=device_class)


@dataclass
class BaseDevice(ABC):
    """Run-level and per-point lifecycle for a physical device adapter."""

    @abstractmethod
    def post_init(self) -> None:
        """Open run-level resources."""

    @abstractmethod
    def init_device(self) -> None:
        """Prepare the device for the current point."""

    @abstractmethod
    def post_close(self) -> None:
        """Close run-level resources."""

    def is_input_device(self) -> bool:
        return isinstance(self, BaseDeviceIn)

    def is_output_device(self) -> bool:
        return isinstance(self, BaseDeviceOut)


@dataclass
class BaseDeviceIn(BaseDevice, Generic[TResult]):
    """Device that appends structured data after each point."""

    result: TResult

    @abstractmethod
    def read_list_dict(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def read(self) -> None:
        rows = self.result.__class__.from_list_dict(self.read_list_dict())
        self.result = cast(TResult, self.result.__iadd__(rows))


@dataclass
class BaseDeviceOut(BaseDevice):
    """Device that accepts output configuration."""

    @abstractmethod
    def config(self) -> None:
        """Apply its current output configuration."""


@dataclass
class BaseDeviceInOut(BaseDeviceIn[TResult], BaseDeviceOut):
    """Device that both accepts configuration and reads results."""


@dataclass
class DeviceList:
    """One experiment-owned collection of devices."""

    def devices(self) -> Iterator[tuple[str, BaseDevice]]:
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, BaseDevice):
                yield item.name, value

    def start_run(self) -> None:
        for _, device in self.devices():
            if isinstance(device, BaseDeviceIn):
                device.result = device.result.__class__()
            device.post_init()

    def init_device(self) -> None:
        for _, device in self.devices():
            device.init_device()

    def read(self) -> None:
        for _, device in self.devices():
            if isinstance(device, BaseDeviceIn):
                device.read()

    def config(self) -> None:
        for _, device in self.devices():
            if isinstance(device, BaseDeviceOut):
                device.config()

    def post_close(self) -> None:
        for _, device in self.devices():
            device.post_close()


device_list_field = field(default_factory=DeviceList)


__all__ = [
    "BaseDevice",
    "BaseDeviceIn",
    "BaseDeviceInOut",
    "BaseDeviceOut",
    "DeviceList",
    "device_field",
    "device_list_field",
]
