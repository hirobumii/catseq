"""
CatSeq MLIR Dialects

这个包包含所有 xDSL/MLIR dialect 定义：
- program_dialect: 控制流层（循环、条件分支）
- program_utils: 非递归遍历工具
- catseq_dialect: Morphism 组合层（将来实现）
- qctrl_dialect: 硬件操作层（将来实现）
- rtmq_dialect: RTMQ 指令层（将来实现）
"""

from .program_dialect import (
    ProgramDialect,
    # Types
    MorphismRefType,
    ConditionType,
    LoopVarType,
    # Operations
    ExecuteOp,
    SequenceOp,
    ForOp,
    IfOp,
    CompareOp,
    LogicalAndOp,
    LogicalOrOp,
    LogicalNotOp,
)
from .program_utils import (
    walk_iterative,
    walk_iterative_with_depth,
    count_operations,
    max_nesting_depth,
)

__all__ = [
    # Dialect
    "ProgramDialect",
    # Types
    "MorphismRefType",
    "ConditionType",
    "LoopVarType",
    # Operations
    "ExecuteOp",
    "SequenceOp",
    "ForOp",
    "IfOp",
    "CompareOp",
    "LogicalAndOp",
    "LogicalOrOp",
    "LogicalNotOp",
    # Utils
    "walk_iterative",
    "walk_iterative_with_depth",
    "count_operations",
    "max_nesting_depth",
]
