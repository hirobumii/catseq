"""
Tree-based symbolic expressions for CatSeq source construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Never, Sequence

from .types import AttrBase, ExprOperand, ItemKey, ScalarLiteral


def _to_expr(value: ExprOperand) -> Expr:
    return value if isinstance(value, Expr) else Expr.const(value)


@dataclass(frozen=True, eq=False)
class Expr:
    kind: str
    value: ScalarLiteral | ItemKey = None
    args: tuple[Expr, ...] = ()

    @staticmethod
    def const(value: ScalarLiteral) -> Expr:
        return Expr("const", value=value)

    @staticmethod
    def input() -> Expr:
        return Expr("input")

    @staticmethod
    def var(name: str) -> Expr:
        return Expr("var", value=name)

    @staticmethod
    def attr(base: AttrBase, name: str) -> Expr:
        return Expr("attr", value=name, args=(_to_expr(base),))

    @staticmethod
    def attr_or(base: AttrBase, name: str, default: ExprOperand) -> Expr:
        return Expr("attr_or", value=name, args=(_to_expr(base), _to_expr(default)))

    @staticmethod
    def item(base: AttrBase, key: ItemKey) -> Expr:
        return Expr("item", value=key, args=(_to_expr(base),))

    @staticmethod
    def time_to_cycles(duration: ExprOperand) -> Expr:
        return Expr("time_to_cycles", args=(_to_expr(duration),))

    def __getattr__(self, name: str) -> Expr:
        if name.startswith("__"):
            raise AttributeError(name)
        return Expr.attr(self, name)

    def __getitem__(self, key: ItemKey) -> Expr:
        return Expr.item(self, key)

    def __iter__(self) -> Never:
        raise TypeError("Symbolic expressions are not iterable.")

    def __bool__(self) -> Never:
        raise TypeError("Symbolic expressions cannot be used as Python booleans.")

    def __add__(self, other: ExprOperand) -> Expr:
        return Expr("add", args=(self, _to_expr(other)))

    def __radd__(self, other: ExprOperand) -> Expr:
        return _to_expr(other) + self

    def __sub__(self, other: ExprOperand) -> Expr:
        return Expr("sub", args=(self, _to_expr(other)))

    def __rsub__(self, other: ExprOperand) -> Expr:
        return _to_expr(other) - self

    def __mul__(self, other: ExprOperand) -> Expr:
        return Expr("mul", args=(self, _to_expr(other)))

    def __rmul__(self, other: ExprOperand) -> Expr:
        return _to_expr(other) * self

    def __truediv__(self, other: ExprOperand) -> Expr:
        return Expr("div", args=(self, _to_expr(other)))

    def __rtruediv__(self, other: ExprOperand) -> Expr:
        return _to_expr(other) / self

    def __floordiv__(self, other: ExprOperand) -> Expr:
        return Expr("floordiv", args=(self, _to_expr(other)))

    def __rfloordiv__(self, other: ExprOperand) -> Expr:
        return _to_expr(other) // self

    def __mod__(self, other: ExprOperand) -> Expr:
        return Expr("mod", args=(self, _to_expr(other)))

    def __rmod__(self, other: ExprOperand) -> Expr:
        return _to_expr(other) % self

    def __and__(self, other: ExprOperand) -> Expr:
        return Expr("bitand", args=(self, _to_expr(other)))

    def __rand__(self, other: ExprOperand) -> Expr:
        return _to_expr(other) & self

    def __or__(self, other: ExprOperand) -> Expr:
        return Expr("bitor", args=(self, _to_expr(other)))

    def __ror__(self, other: ExprOperand) -> Expr:
        return _to_expr(other) | self

    def __xor__(self, other: ExprOperand) -> Expr:
        return Expr("bitxor", args=(self, _to_expr(other)))

    def __rxor__(self, other: ExprOperand) -> Expr:
        return _to_expr(other) ^ self

    def __lshift__(self, other: ExprOperand) -> Expr:
        return Expr("lshift", args=(self, _to_expr(other)))

    def __rlshift__(self, other: ExprOperand) -> Expr:
        return _to_expr(other) << self

    def __rshift__(self, other: ExprOperand) -> Expr:
        return Expr("rshift", args=(self, _to_expr(other)))

    def __rrshift__(self, other: ExprOperand) -> Expr:
        return _to_expr(other) >> self

    def __neg__(self) -> Expr:
        return Expr("neg", args=(self,))

    def __invert__(self) -> Expr:
        return Expr("invert", args=(self,))

    def __eq__(self, other: object) -> Expr:  # type: ignore[override]
        return Expr("eq", args=(self, _to_expr(other)))

    def __ne__(self, other: object) -> Expr:  # type: ignore[override]
        return Expr("ne", args=(self, _to_expr(other)))

    def __lt__(self, other: ExprOperand) -> Expr:
        return Expr("lt", args=(self, _to_expr(other)))

    def __le__(self, other: ExprOperand) -> Expr:
        return Expr("le", args=(self, _to_expr(other)))

    def __gt__(self, other: ExprOperand) -> Expr:
        return Expr("gt", args=(self, _to_expr(other)))

    def __ge__(self, other: ExprOperand) -> Expr:
        return Expr("ge", args=(self, _to_expr(other)))

    def resolve(
        self,
        input_value: object,
        env: Mapping[str, object] | None = None,
    ) -> object:
        if self.kind == "const":
            return self.value
        if self.kind == "input":
            return input_value
        if self.kind == "var":
            if env is None:
                raise KeyError(f"Runtime variable {self.value!r} is not available.")
            return env[str(self.value)]
        if self.kind == "attr":
            return getattr(self.args[0].resolve(input_value, env), str(self.value))
        if self.kind == "attr_or":
            return getattr(
                self.args[0].resolve(input_value, env),
                str(self.value),
                self.args[1].resolve(input_value, env),
            )
        if self.kind == "item":
            base = self.args[0].resolve(input_value, env)
            key = self.value
            if isinstance(base, Mapping):
                return base[key]
            if isinstance(base, Sequence) and not isinstance(base, (str, bytes)):
                return base[key]  # type: ignore[index]
            return getattr(base, str(key))
        if self.kind == "time_to_cycles":
            from ..time_utils import time_to_cycles

            return time_to_cycles(self.args[0].resolve(input_value, env))
        if self.kind == "add":
            return self.args[0].resolve(input_value, env) + self.args[1].resolve(input_value, env)
        if self.kind == "sub":
            return self.args[0].resolve(input_value, env) - self.args[1].resolve(input_value, env)
        if self.kind == "mul":
            return self.args[0].resolve(input_value, env) * self.args[1].resolve(input_value, env)
        if self.kind == "div":
            return self.args[0].resolve(input_value, env) / self.args[1].resolve(input_value, env)
        if self.kind == "floordiv":
            return self.args[0].resolve(input_value, env) // self.args[1].resolve(input_value, env)
        if self.kind == "mod":
            return self.args[0].resolve(input_value, env) % self.args[1].resolve(input_value, env)
        if self.kind == "bitand":
            return self.args[0].resolve(input_value, env) & self.args[1].resolve(input_value, env)
        if self.kind == "bitor":
            return self.args[0].resolve(input_value, env) | self.args[1].resolve(input_value, env)
        if self.kind == "bitxor":
            return self.args[0].resolve(input_value, env) ^ self.args[1].resolve(input_value, env)
        if self.kind == "lshift":
            return self.args[0].resolve(input_value, env) << self.args[1].resolve(input_value, env)
        if self.kind == "rshift":
            return self.args[0].resolve(input_value, env) >> self.args[1].resolve(input_value, env)
        if self.kind == "neg":
            return -self.args[0].resolve(input_value, env)
        if self.kind == "invert":
            return ~self.args[0].resolve(input_value, env)
        if self.kind == "eq":
            return self.args[0].resolve(input_value, env) == self.args[1].resolve(input_value, env)
        if self.kind == "ne":
            return self.args[0].resolve(input_value, env) != self.args[1].resolve(input_value, env)
        if self.kind == "lt":
            return self.args[0].resolve(input_value, env) < self.args[1].resolve(input_value, env)
        if self.kind == "le":
            return self.args[0].resolve(input_value, env) <= self.args[1].resolve(input_value, env)
        if self.kind == "gt":
            return self.args[0].resolve(input_value, env) > self.args[1].resolve(input_value, env)
        if self.kind == "ge":
            return self.args[0].resolve(input_value, env) >= self.args[1].resolve(input_value, env)
        raise ValueError(f"Unsupported symbolic expression kind: {self.kind}")


def input_state() -> Expr:
    return Expr.input()


def var(name: str) -> Expr:
    return Expr.var(name)
