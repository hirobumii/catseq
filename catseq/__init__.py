"""CatSeq restricted-source DSL and native compiler adapter."""

from .compilation import (
    CatSeqCompileError,
    OASMCall,
    OASMCompileResult,
    compile_entry,
    execute_oasm_calls,
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
    cycles_to_time,
    cycles_to_us,
    ms,
    mu,
    ns,
    s,
    time_to_cycles,
    us,
    us_to_cycles,
)
from .types import Board, Channel, ChannelType, State

__version__ = "0.3.0.dev0"

__all__ = [
    "Board",
    "CatSeqCompileError",
    "Channel",
    "ChannelType",
    "CompilerDefinition",
    "CompilerOnlyError",
    "Morphism",
    "MorphismDef",
    "MorphismTemplate",
    "OASMCall",
    "OASMCompileResult",
    "State",
    "atomic_morphism",
    "arena_build",
    "compile_entry",
    "cycles_to_time",
    "cycles_to_us",
    "execute_oasm_calls",
    "identity",
    "ms",
    "morphism_template",
    "mu",
    "ns",
    "repeat_morphism",
    "s",
    "time_to_cycles",
    "us",
    "us_to_cycles",
]
