"""
Expression AST for conditions and computations.
"""

from dataclasses import dataclass
from typing import Union
from .variables import RuntimeVar, CompileTimeParam


@dataclass(frozen=True)
class Expr:
    """表达式基类"""
    pass


@dataclass(frozen=True)
class VarRef(Expr):
    """变量引用

    例如：adc_value (在条件中使用)
    """
    var: RuntimeVar


@dataclass(frozen=True)
class ConstExpr(Expr):
    """常量表达式

    例如：500, 1000 (在条件中使用)
    """
    value: int | float


@dataclass(frozen=True)
class BinOp(Expr):
    """二元操作

    例如：adc_value > 500, x + y, flag && ready
    """
    op: str  # ">", "<", ">=", "<=", "==", "!=", "&&", "||", "+", "-", "*", "/"
    left: Expr
    right: Expr


@dataclass(frozen=True)
class UnaryOp(Expr):
    """一元操作

    例如：!flag, -x
    """
    op: str  # "!", "-"
    operand: Expr


@dataclass(frozen=True)
class Condition:
    """条件表达式（用于 if/cond）

    内部表示为表达式树，支持组合和逻辑运算
    """
    _expr: Expr

    def __and__(self, other: 'Condition') -> 'Condition':
        """逻辑与: cond1 & cond2"""
        return Condition(BinOp("&&", self._expr, other._expr))

    def __or__(self, other: 'Condition') -> 'Condition':
        """逻辑或: cond1 | cond2"""
        return Condition(BinOp("||", self._expr, other._expr))

    def negate(self) -> 'Condition':
        """逻辑非: cond.negate()"""
        return Condition(UnaryOp("!", self._expr))

    @staticmethod
    def from_comparison(var: RuntimeVar, op: str, value: int | float) -> 'Condition':
        """从比较操作创建条件

        例如：Condition.from_comparison(adc_value, ">", 500)
        """
        left = VarRef(var)
        right = ConstExpr(value)
        return Condition(BinOp(op, left, right))
