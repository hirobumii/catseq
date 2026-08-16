"""CatSeq restricted-source DSL and native runtime adapter."""

from ._native_record import replace
from .compilation import CatSeqRuntimeError
from .morphism import (
    CompilerDefinition,
    CompilerOnlyError,
    Id,
    Morphism,
    Wait,
    atomic_morphism,
    compute,
    kernel,
    morphism,
    repeat_morphism,
)
from .time_utils import (
    Duration,
    cycles,
    cycles_to_time,
    cycles_to_us,
    ms,
    ns,
    s,
    time_to_cycles,
    us,
    us_to_cycles,
)
from .types import Board, Channel, ChannelType, State

int32 = int

__version__ = "0.4.2"

__all__ = [
    "Board",
    "CatSeqRuntimeError",
    "Channel",
    "ChannelType",
    "CompilerDefinition",
    "CompilerOnlyError",
    "Duration",
    "Id",
    "Morphism",
    "State",
    "Wait",
    "atomic_morphism",
    "compute",
    "cycles",
    "cycles_to_time",
    "cycles_to_us",
    "int32",
    "kernel",
    "morphism",
    "ms",
    "ns",
    "repeat_morphism",
    "replace",
    "s",
    "time_to_cycles",
    "us",
    "us_to_cycles",
]
