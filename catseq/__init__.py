"""CatSeq restricted-source DSL and native compiler adapter."""

from .compilation import (
    CatSeqCompileError,
    CatSeqRuntimeError,
    OASMCall,
    OASMCompileResult,
    assemble_oasm_calls,
    compile_entry,
    execute_oasm_program,
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

__version__ = "0.3.1.dev0"

__all__ = [
    "Board",
    "CatSeqCompileError",
    "CatSeqRuntimeError",
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
    "assemble_oasm_calls",
    "compile_entry",
    "cycles_to_time",
    "cycles_to_us",
    "execute_oasm_program",
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
