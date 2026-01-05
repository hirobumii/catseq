"""
Program AST node definitions.
"""

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class ProgramNode:
    """Program AST 基类"""
    pass


@dataclass(frozen=True)
class MorphismStmt(ProgramNode):
    """执行 Morphism 语句

    例如：execute(pulse)
    """
    morphism: 'Morphism'  # type: ignore


@dataclass(frozen=True)
class SequenceStmt(ProgramNode):
    """顺序执行多个语句

    例如：program1 >> program2 >> program3
    """
    statements: tuple[ProgramNode, ...]


@dataclass(frozen=True)
class ForLoopStmt(ProgramNode):
    """For 循环语句

    例如：program.replicate(100)
    """
    loop_var: str  # 循环变量名（如 "_" 表示不使用）
    count: Union[int, 'CompileTimeParam']  # type: ignore  # 循环次数（固定或编译时参数）
    body: ProgramNode  # 循环体


@dataclass(frozen=True)
class IfStmt(ProgramNode):
    """条件分支语句

    例如：cond([(adc_value > 500, execute(pulse_high))], default=execute(pulse_low))
    """
    condition: 'Condition'  # type: ignore  # 条件表达式
    then_branch: ProgramNode  # then 分支
    else_branch: ProgramNode | None = None  # else 分支（可选）
