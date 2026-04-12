"""
Symbolic expression helpers for CatSeq V2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Never, Self, Sequence

from catseq.types.common import State

from .typing import AttrBase, ExprOperand, ItemKey, ScalarValue


def _to_expr(value: ExprOperand) -> SymExpr:
    return value if isinstance(value, SymExpr) else SymExpr.const(value)


@dataclass(frozen=True)
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

    def __neg__(self) -> Self:
        return SymExpr("neg", args=(self,))

    def resolve(self, input_state: object) -> object:
        if self.kind == "const":
            return self.value
        if self.kind == "input":
            return input_state
        if self.kind == "attr":
            return getattr(self.args[0].resolve(input_state), self.value)
        if self.kind == "attr_or":
            return getattr(self.args[0].resolve(input_state), self.value, self.args[1].resolve(input_state))
        if self.kind == "item":
            base = self.args[0].resolve(input_state)
            key = self.value
            if isinstance(base, Mapping):
                return base[key]
            if isinstance(base, Sequence) and not isinstance(base, (str, bytes)):
                return base[key]
            return getattr(base, key)
        if self.kind == "add":
            return self.args[0].resolve(input_state) + self.args[1].resolve(input_state)
        if self.kind == "sub":
            return self.args[0].resolve(input_state) - self.args[1].resolve(input_state)
        if self.kind == "mul":
            return self.args[0].resolve(input_state) * self.args[1].resolve(input_state)
        if self.kind == "div":
            return self.args[0].resolve(input_state) / self.args[1].resolve(input_state)
        if self.kind == "neg":
            return -self.args[0].resolve(input_state)
        raise ValueError(f"Unsupported symbolic expression kind: {self.kind}")


def input_state() -> SymExpr:
    return SymExpr.input()


def resolve_value(value: object, state: object) -> object:
    if isinstance(value, SymExpr):
        return value.resolve(state)
    if isinstance(value, tuple):
        return tuple(resolve_value(item, state) for item in value)
    if isinstance(value, list):
        return [resolve_value(item, state) for item in value]
    if isinstance(value, dict):
        return {key: resolve_value(item, state) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        values = {
            key: resolve_value(getattr(value, key), state)
            for key in value.__dataclass_fields__
        }
        return type(value)(**values)
    return value
