"""
CatSeq V2 Compiler Architecture - MLIR/xDSL Based

This module implements a three-layer dialect architecture for compiling
quantum control programs:

1. catseq dialect - High-level Morphism abstraction (Category Theory)
2. qctrl dialect - Mid-level quantum control operations (TTL, RWG, RSP)
3. rtmq dialect - Low-level RTMQ hardware instructions

Version: 0.3.0-dev (MLIR Refactor)
Development Timeline: 13 weeks (Phase 0-5)
"""

__version__ = "0.3.0-dev"

# Dialects
from .dialects.catseq_dialect import (
    CatseqDialect,
    ChannelType,
    MorphismType,
    CompositeMorphismType,
    ComposOp,
    TensorOp,
    IdentityOp,
    AtomicOp,
)
# from .dialects.qctrl_dialect import QctrlDialect
# from .dialects.rtmq_dialect import RTMQDialect

# Lowering passes
# from .lowering.program_to_catseq import ProgramToCatseqLowering
# from .lowering.catseq_to_qctrl import CatseqToQctrlLowering
# from .lowering.qctrl_to_rtmq import QctrlToRTMQLowering

# Code generation
# from .codegen.rtmq_to_oasm import RTMQToOASMEmitter

# Optimization passes
# from .optimization.rwg_pipeline import RWGPipelineOptimization
# from .optimization.ttl_merge import TTLMergeOptimization
# from .optimization.dead_code import DeadCodeElimination

# V2 Compiler entry point
# from .compiler_v2 import compile_to_oasm_calls_v2

__all__ = [
    "__version__",
    # Dialects
    "CatseqDialect",
    # Types
    "ChannelType",
    "MorphismType",
    "CompositeMorphismType",
    # Operations
    "ComposOp",
    "TensorOp",
    "IdentityOp",
    "AtomicOp",
]
