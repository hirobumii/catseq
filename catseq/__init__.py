"""CatSeq restricted-source DSL and native compiler adapter."""

from ._native_record import replace
from .compiler import Compiler, CompiledSequence
from .compilation import (
    CatSeqCompileError,
    CatSeqRuntimeError,
    EthernetRuntime,
)
from .morphism import (
    CompilerDefinition,
    CompilerOnlyError,
    Morphism,
    MorphismDef,
    MorphismTemplate,
    atomic_morphism,
    arena_build,
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

__version__ = "0.4.1"

__all__ = [
    "Board",
    "CatSeqCompileError",
    "CatSeqRuntimeError",
    "Channel",
    "ChannelType",
    "CompiledSequence",
    "Compiler",
    "CompilerDefinition",
    "CompilerOnlyError",
    "EthernetRuntime",
    "Duration",
    "Morphism",
    "MorphismDef",
    "MorphismTemplate",
    "State",
    "atomic_morphism",
    "arena_build",
    "cycles",
    "cycles_to_time",
    "cycles_to_us",
    "identity",
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
