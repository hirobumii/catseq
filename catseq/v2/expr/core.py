"""
Symbolic expression helpers for CatSeq V2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Never, Self, Sequence

from catseq.types.common import State

from .types import AttrBase, ExprOperand, ItemKey, ScalarValue


def _to_expr(value: ExprOperand) -> SymExpr:
    return value if isinstance(value, SymExpr) else SymExpr.const(value)


@dataclass(frozen=True, eq=False)
class SymExpr:
    kind: str
    value: ScalarValue | ItemKey = None
    args: tuple[Self, ...] = ()

    @staticmethod
    def const(value: State | ScalarValue) -> Self:
        return SymExpr("const", value=value)

    @staticmethod
    def input() -> Self:
        return SymExpr("input")

    @staticmethod
    def var(name: str) -> Self:
        return SymExpr("var", value=name)

    @staticmethod
    def attr(base: AttrBase, name: str) -> Self:
        return SymExpr("attr", value=name, args=(_to_expr(base),))

    @staticmethod
    def attr_or(base: AttrBase, name: str, default: ExprOperand) -> Self:
        return SymExpr("attr_or", value=name, args=(_to_expr(base), _to_expr(default)))

    @staticmethod
    def item(base: AttrBase, key: ItemKey) -> Self:
        return SymExpr("item", value=key, args=(_to_expr(base),))

    def __getattr__(self, name: str) -> Self:
        if name.startswith("__"):
            raise AttributeError(name)
        return SymExpr.attr(self, name)

    def __getitem__(self, key: ItemKey) -> Self:
        return SymExpr.item(self, key)

    def __iter__(self) -> Never:
        raise TypeError("Symbolic expressions are not iterable.")

    def __bool__(self) -> Never:
        raise TypeError("Symbolic expressions cannot be used as Python booleans.")

    def __add__(self, other: ExprOperand) -> Self:
        return SymExpr("add", args=(self, _to_expr(other)))

    def __radd__(self, other: ExprOperand) -> Self:
        return _to_expr(other) + self

    def __sub__(self, other: ExprOperand) -> Self:
        return SymExpr("sub", args=(self, _to_expr(other)))

    def __rsub__(self, other: ExprOperand) -> Self:
        return _to_expr(other) - self

    def __mul__(self, other: ExprOperand) -> Self:
        return SymExpr("mul", args=(self, _to_expr(other)))

    def __rmul__(self, other: ExprOperand) -> Self:
        return _to_expr(other) * self

    def __truediv__(self, other: ExprOperand) -> Self:
        return SymExpr("div", args=(self, _to_expr(other)))

    def __rtruediv__(self, other: ExprOperand) -> Self:
        return _to_expr(other) / self

    def __floordiv__(self, other: ExprOperand) -> Self:
        return SymExpr("floordiv", args=(self, _to_expr(other)))

    def __rfloordiv__(self, other: ExprOperand) -> Self:
        return _to_expr(other) // self

    def __mod__(self, other: ExprOperand) -> Self:
        return SymExpr("mod", args=(self, _to_expr(other)))

    def __rmod__(self, other: ExprOperand) -> Self:
        return _to_expr(other) % self

    def __and__(self, other: ExprOperand) -> Self:
        return SymExpr("bitand", args=(self, _to_expr(other)))

    def __rand__(self, other: ExprOperand) -> Self:
        return _to_expr(other) & self

    def __or__(self, other: ExprOperand) -> Self:
        return SymExpr("bitor", args=(self, _to_expr(other)))

    def __ror__(self, other: ExprOperand) -> Self:
        return _to_expr(other) | self

    def __xor__(self, other: ExprOperand) -> Self:
        return SymExpr("bitxor", args=(self, _to_expr(other)))

    def __rxor__(self, other: ExprOperand) -> Self:
        return _to_expr(other) ^ self

    def __lshift__(self, other: ExprOperand) -> Self:
        return SymExpr("lshift", args=(self, _to_expr(other)))

    def __rlshift__(self, other: ExprOperand) -> Self:
        return _to_expr(other) << self

    def __rshift__(self, other: ExprOperand) -> Self:
        return SymExpr("rshift", args=(self, _to_expr(other)))

    def __rrshift__(self, other: ExprOperand) -> Self:
        return _to_expr(other) >> self

    def __neg__(self) -> Self:
        return SymExpr("neg", args=(self,))

    def __invert__(self) -> Self:
        return SymExpr("invert", args=(self,))

    def __eq__(self, other: object) -> Self:  # type: ignore[override]
        return SymExpr("eq", args=(self, _to_expr(other)))

    def __ne__(self, other: object) -> Self:  # type: ignore[override]
        return SymExpr("ne", args=(self, _to_expr(other)))

    def __lt__(self, other: ExprOperand) -> Self:
        return SymExpr("lt", args=(self, _to_expr(other)))

    def __le__(self, other: ExprOperand) -> Self:
        return SymExpr("le", args=(self, _to_expr(other)))

    def __gt__(self, other: ExprOperand) -> Self:
        return SymExpr("gt", args=(self, _to_expr(other)))

    def __ge__(self, other: ExprOperand) -> Self:
        return SymExpr("ge", args=(self, _to_expr(other)))

    def resolve(
        self,
        input_state: object,
        env: Mapping[str, object] | None = None,
    ) -> object:
        if self.kind == "const":
            return self.value
        if self.kind == "input":
            return input_state
        if self.kind == "var":
            if env is None:
                raise KeyError(f"Runtime variable {self.value!r} is not available.")
            return env[self.value]
        if self.kind == "attr":
            return getattr(self.args[0].resolve(input_state, env), self.value)
        if self.kind == "attr_or":
            return getattr(
                self.args[0].resolve(input_state, env),
                self.value,
                self.args[1].resolve(input_state, env),
            )
        if self.kind == "item":
            base = self.args[0].resolve(input_state, env)
            key = self.value
            if isinstance(base, Mapping):
                return base[key]
            if isinstance(base, Sequence) and not isinstance(base, (str, bytes)):
                return base[key]
            return getattr(base, key)
        if self.kind == "add":
            return self.args[0].resolve(input_state, env) + self.args[1].resolve(input_state, env)
        if self.kind == "sub":
            return self.args[0].resolve(input_state, env) - self.args[1].resolve(input_state, env)
        if self.kind == "mul":
            return self.args[0].resolve(input_state, env) * self.args[1].resolve(input_state, env)
        if self.kind == "div":
            return self.args[0].resolve(input_state, env) / self.args[1].resolve(input_state, env)
        if self.kind == "floordiv":
            return self.args[0].resolve(input_state, env) // self.args[1].resolve(input_state, env)
        if self.kind == "mod":
            return self.args[0].resolve(input_state, env) % self.args[1].resolve(input_state, env)
        if self.kind == "bitand":
            return self.args[0].resolve(input_state, env) & self.args[1].resolve(input_state, env)
        if self.kind == "bitor":
            return self.args[0].resolve(input_state, env) | self.args[1].resolve(input_state, env)
        if self.kind == "bitxor":
            return self.args[0].resolve(input_state, env) ^ self.args[1].resolve(input_state, env)
        if self.kind == "lshift":
            return self.args[0].resolve(input_state, env) << self.args[1].resolve(input_state, env)
        if self.kind == "rshift":
            return self.args[0].resolve(input_state, env) >> self.args[1].resolve(input_state, env)
        if self.kind == "neg":
            return -self.args[0].resolve(input_state, env)
        if self.kind == "invert":
            return ~self.args[0].resolve(input_state, env)
        if self.kind == "eq":
            return self.args[0].resolve(input_state, env) == self.args[1].resolve(input_state, env)
        if self.kind == "ne":
            return self.args[0].resolve(input_state, env) != self.args[1].resolve(input_state, env)
        if self.kind == "lt":
            return self.args[0].resolve(input_state, env) < self.args[1].resolve(input_state, env)
        if self.kind == "le":
            return self.args[0].resolve(input_state, env) <= self.args[1].resolve(input_state, env)
        if self.kind == "gt":
            return self.args[0].resolve(input_state, env) > self.args[1].resolve(input_state, env)
        if self.kind == "ge":
            return self.args[0].resolve(input_state, env) >= self.args[1].resolve(input_state, env)
        raise ValueError(f"Unsupported symbolic expression kind: {self.kind}")


def input_state() -> SymExpr:
    return SymExpr.input()


def var(name: str) -> SymExpr:
    return SymExpr.var(name)


def resolve_value(
    value: object,
    state: object,
    env: Mapping[str, object] | None = None,
) -> object:
    if isinstance(value, SymExpr):
        return value.resolve(state, env)
    if isinstance(value, tuple):
        return tuple(resolve_value(item, state, env) for item in value)
    if isinstance(value, list):
        return [resolve_value(item, state, env) for item in value]
    if isinstance(value, dict):
        return {key: resolve_value(item, state, env) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        values = {
            key: resolve_value(getattr(value, key), state, env)
            for key in value.__dataclass_fields__
        }
        return type(value)(**values)
    return value
