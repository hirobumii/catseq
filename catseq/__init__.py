"""CatSeq restricted-source DSL and native runtime adapter."""

from ._native_record import replace
from .compilation import CatSeqRuntimeError
from .morphism import (
    CompilerDefinition,
    CompilerOnlyError,
    Morphism,
    MorphismDef,
    MorphismTemplate,
    atomic_morphism,
    compute,
    identity,
    morphism_template,
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
    "Morphism",
    "MorphismDef",
    "MorphismTemplate",
    "State",
    "atomic_morphism",
    "compute",
    "cycles",
    "cycles_to_time",
    "cycles_to_us",
    "identity",
    "int32",
    "ms",
    "morphism_template",
    "ns",
    "repeat_morphism",
    "replace",
    "s",
    "time_to_cycles",
    "us",
    "us_to_cycles",
]
