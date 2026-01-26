"""CatSeq V2 Value System - Handle-based

提供符号值系统，支持字面量、变量、表达式。
所有值都存储在 Rust Arena 中，Python 对象只持有轻量级 Handle（ValueId）。

使用示例：
    >>> from catseq.v2.values import var, literal
    >>>
    >>> # 创建变量
    >>> x = var("x")
    >>> y = var("y", type_hint="float32")
    >>>
    >>> # 算术运算
    >>> z = x + 10
    >>> w = y * 2 - 5
    >>>
    >>> # 比较运算
    >>> cond = x > 0
"""

from __future__ import annotations

from typing import Union

from catseq.v2.context import get_arena

# 类型别名
Numeric = Union[int, float]


class Value:
    """Value: Arena 中值的轻量级 Handle

    只持有 node_id，所有数据存储在 Rust Arena 中。
    支持算术、位、比较运算符重载。
    """

    __slots__ = ("_id",)

    def __init__(self, node_id: int):
        self._id = node_id

    @property
    def id(self) -> int:
        """获取 Arena 中的 ValueId"""
        return self._id

    # =========================================================================
    # 算术运算
    # =========================================================================

    def __add__(self, other: Union[Value, Numeric]) -> Value:
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.binary_expr(self._id, "+", rhs_id)
        return Value(new_id)

    def __radd__(self, other: Numeric) -> Value:
        arena = get_arena()
        lhs_id = arena.literal(int(other)) if isinstance(other, int) else arena.literal_float(other)
        new_id = arena.binary_expr(lhs_id, "+", self._id)
        return Value(new_id)

    def __sub__(self, other: Union[Value, Numeric]) -> Value:
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.binary_expr(self._id, "-", rhs_id)
        return Value(new_id)

    def __rsub__(self, other: Numeric) -> Value:
        arena = get_arena()
        lhs_id = arena.literal(int(other)) if isinstance(other, int) else arena.literal_float(other)
        new_id = arena.binary_expr(lhs_id, "-", self._id)
        return Value(new_id)

    def __mul__(self, other: Union[Value, Numeric]) -> Value:
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.binary_expr(self._id, "*", rhs_id)
        return Value(new_id)

    def __rmul__(self, other: Numeric) -> Value:
        arena = get_arena()
        lhs_id = arena.literal(int(other)) if isinstance(other, int) else arena.literal_float(other)
        new_id = arena.binary_expr(lhs_id, "*", self._id)
        return Value(new_id)

    def __truediv__(self, other: Union[Value, Numeric]) -> Value:
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.binary_expr(self._id, "/", rhs_id)
        return Value(new_id)

    def __rtruediv__(self, other: Numeric) -> Value:
        arena = get_arena()
        lhs_id = arena.literal(int(other)) if isinstance(other, int) else arena.literal_float(other)
        new_id = arena.binary_expr(lhs_id, "/", self._id)
        return Value(new_id)

    def __mod__(self, other: Union[Value, Numeric]) -> Value:
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.binary_expr(self._id, "%", rhs_id)
        return Value(new_id)

    def __neg__(self) -> Value:
        arena = get_arena()
        new_id = arena.unary_expr("-", self._id)
        return Value(new_id)

    # =========================================================================
    # 位运算
    # =========================================================================

    def __and__(self, other: Union[Value, int]) -> Value:
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.binary_expr(self._id, "&", rhs_id)
        return Value(new_id)

    def __rand__(self, other: int) -> Value:
        arena = get_arena()
        lhs_id = arena.literal(other)
        new_id = arena.binary_expr(lhs_id, "&", self._id)
        return Value(new_id)

    def __or__(self, other: Union[Value, int]) -> Value:
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.binary_expr(self._id, "|", rhs_id)
        return Value(new_id)

    def __ror__(self, other: int) -> Value:
        arena = get_arena()
        lhs_id = arena.literal(other)
        new_id = arena.binary_expr(lhs_id, "|", self._id)
        return Value(new_id)

    def __xor__(self, other: Union[Value, int]) -> Value:
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.binary_expr(self._id, "^", rhs_id)
        return Value(new_id)

    def __lshift__(self, other: Union[Value, int]) -> Value:
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.binary_expr(self._id, "<<", rhs_id)
        return Value(new_id)

    def __rshift__(self, other: Union[Value, int]) -> Value:
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.binary_expr(self._id, ">>", rhs_id)
        return Value(new_id)

    def __invert__(self) -> Value:
        arena = get_arena()
        new_id = arena.unary_expr("~", self._id)
        return Value(new_id)

    # =========================================================================
    # 比较运算
    # =========================================================================

    def __gt__(self, other: Union[Value, Numeric]) -> Condition:
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.condition(self._id, ">", rhs_id)
        return Condition(new_id)

    def __lt__(self, other: Union[Value, Numeric]) -> Condition:
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.condition(self._id, "<", rhs_id)
        return Condition(new_id)

    def __ge__(self, other: Union[Value, Numeric]) -> Condition:
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.condition(self._id, ">=", rhs_id)
        return Condition(new_id)

    def __le__(self, other: Union[Value, Numeric]) -> Condition:
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.condition(self._id, "<=", rhs_id)
        return Condition(new_id)

    def __eq__(self, other: Union[Value, Numeric]) -> Condition:  # type: ignore[override]
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.condition(self._id, "==", rhs_id)
        return Condition(new_id)

    def __ne__(self, other: Union[Value, Numeric]) -> Condition:  # type: ignore[override]
        arena = get_arena()
        rhs_id = _ensure_value_id(other)
        new_id = arena.condition(self._id, "!=", rhs_id)
        return Condition(new_id)

    def __repr__(self) -> str:
        return f"Value(id={self._id})"


class Variable(Value):
    """Variable: 带名称的 Value

    代表硬件寄存器或编译时符号。
    """

    __slots__ = ("_name",)

    def __init__(self, node_id: int, name: str):
        super().__init__(node_id)
        self._name = name

    @property
    def name(self) -> str:
        """获取变量名"""
        return self._name

    def __repr__(self) -> str:
        return f"Variable({self._name!r}, id={self._id})"


class Condition:
    """Condition: 条件表达式 Handle

    比较运算的结果，用于 if_/match_ 等控制流。
    """

    __slots__ = ("_id",)

    def __init__(self, node_id: int):
        self._id = node_id

    @property
    def id(self) -> int:
        """获取 Arena 中的 ValueId"""
        return self._id

    def __and__(self, other: Condition) -> Condition:
        """逻辑与 (&&)"""
        arena = get_arena()
        new_id = arena.logical_expr(self._id, "and", other._id)
        return Condition(new_id)

    def __or__(self, other: Condition) -> Condition:
        """逻辑或 (||)"""
        arena = get_arena()
        new_id = arena.logical_expr(self._id, "or", other._id)
        return Condition(new_id)

    def __invert__(self) -> Condition:
        """逻辑非 (!)"""
        arena = get_arena()
        new_id = arena.logical_expr(self._id, "not", None)
        return Condition(new_id)

    def __repr__(self) -> str:
        return f"Condition(id={self._id})"


# =============================================================================
# Helper Functions
# =============================================================================

def _ensure_value_id(x: Union[Value, Numeric]) -> int:
    """确保返回 Arena 中的 ValueId"""
    if isinstance(x, Value):
        return x.id
    arena = get_arena()
    if isinstance(x, int):
        return arena.literal(x)
    else:
        return arena.literal_float(float(x))


def literal(value: Numeric) -> Value:
    """创建字面量 Value

    Args:
        value: 整数或浮点数值

    Returns:
        Value: 新创建的 Value Handle
    """
    arena = get_arena()
    if isinstance(value, int):
        node_id = arena.literal(value)
    else:
        node_id = arena.literal_float(float(value))
    return Value(node_id)


def var(name: str, type_hint: str = "int32") -> Variable:
    """创建变量

    如果同名变量已存在，返回已有的 Variable（保证唯一性）。

    Args:
        name: 变量名
        type_hint: 类型提示 ("int32", "int64", "float32", "float64", "bool")

    Returns:
        Variable: 新创建或已存在的 Variable Handle
    """
    arena = get_arena()
    node_id = arena.variable(name, type_hint)
    return Variable(node_id, name)
