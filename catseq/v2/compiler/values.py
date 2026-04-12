"""
Shared value preparation helpers for CatSeq v2 compiler IR.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import is_dataclass
from operator import add, and_, eq, floordiv, ge, getitem, gt, invert, le, lshift, lt, mod, mul, ne, neg, or_, rshift, sub, truediv, xor

from catseq.v2.expr import SymExpr
from catseq.v2.expr.types import ValueLike


def collect_value_free_vars(value: ValueLike) -> frozenset[str]:
    if isinstance(value, SymExpr):
        return _collect_expr_free_vars(value)
    if isinstance(value, tuple):
        free_vars: set[str] = set()
        for item in value:
            free_vars.update(collect_value_free_vars(item))
        return frozenset(free_vars)
    if isinstance(value, list):
        free_vars: set[str] = set()
        for item in value:
            free_vars.update(collect_value_free_vars(item))
        return frozenset(free_vars)
    if isinstance(value, dict):
        free_vars: set[str] = set()
        for item in value.values():
            free_vars.update(collect_value_free_vars(item))
        return frozenset(free_vars)
    if is_dataclass(value):
        free_vars: set[str] = set()
        for field_name in value.__dataclass_fields__:
            free_vars.update(collect_value_free_vars(getattr(value, field_name)))
        return frozenset(free_vars)
    return frozenset()


def partially_prepare_value(value: ValueLike, state: ValueLike | None) -> ValueLike:
    if isinstance(value, SymExpr):
        return _partially_prepare_expr(value, state)
    if isinstance(value, tuple):
        return tuple(partially_prepare_value(item, state) for item in value)
    if isinstance(value, list):
        return [partially_prepare_value(item, state) for item in value]
    if isinstance(value, dict):
        return {key: partially_prepare_value(item, state) for key, item in value.items()}
    if is_dataclass(value):
        fields = {
            field_name: partially_prepare_value(getattr(value, field_name), state)
            for field_name in value.__dataclass_fields__
        }
        return type(value)(**fields)
    return value


def dump_prepared_value(value: ValueLike) -> object:
    if isinstance(value, SymExpr):
        return {
            "sym": value.kind,
            "value": value.value,
            "args": tuple(dump_prepared_value(arg) for arg in value.args),
        }
    if isinstance(value, tuple):
        return tuple(dump_prepared_value(item) for item in value)
    if isinstance(value, list):
        return [dump_prepared_value(item) for item in value]
    if isinstance(value, dict):
        return {key: dump_prepared_value(item) for key, item in value.items()}
    if is_dataclass(value):
        return {
            "type": type(value).__name__,
            "fields": {
                field_name: dump_prepared_value(getattr(value, field_name))
                for field_name in value.__dataclass_fields__
            },
        }
    return value


def _exprify(value: ValueLike) -> SymExpr:
    if isinstance(value, SymExpr):
        return value
    return SymExpr.const(value)


def _collect_expr_free_vars(expr: SymExpr) -> frozenset[str]:
    if expr.kind == "var":
        return frozenset({str(expr.value)})
    free_vars: set[str] = set()
    for arg in expr.args:
        free_vars.update(_collect_expr_free_vars(arg))
    return frozenset(free_vars)


def _is_concrete(value: ValueLike) -> bool:
    return not collect_value_free_vars(value)


def _partially_prepare_expr(expr: SymExpr, state: ValueLike | None) -> ValueLike:
    match expr.kind:
        case "const":
            return expr.value
        case "input":
            if state is None:
                raise ValueError("input_state() requires a state context during preparation.")
            return state
        case "var":
            return expr
        case "attr":
            base = partially_prepare_value(expr.args[0], state)
            if _is_concrete(base):
                return getattr(base, str(expr.value))
            return SymExpr("attr", value=expr.value, args=(_exprify(base),))
        case "attr_or":
            base = partially_prepare_value(expr.args[0], state)
            default = partially_prepare_value(expr.args[1], state)
            if _is_concrete(base):
                return getattr(base, str(expr.value), default)
            return SymExpr("attr_or", value=expr.value, args=(_exprify(base), _exprify(default)))
        case "item":
            base = partially_prepare_value(expr.args[0], state)
            if _is_concrete(base):
                return _get_item(base, expr.value)
            return SymExpr("item", value=expr.value, args=(_exprify(base),))
        case "neg":
            return _partially_apply_unary(expr, state, neg)
        case "invert":
            return _partially_apply_unary(expr, state, invert)
        case "add":
            return _partially_apply_binary(expr, state, add)
        case "sub":
            return _partially_apply_binary(expr, state, sub)
        case "mul":
            return _partially_apply_binary(expr, state, mul)
        case "div":
            return _partially_apply_binary(expr, state, truediv)
        case "floordiv":
            return _partially_apply_binary(expr, state, floordiv)
        case "mod":
            return _partially_apply_binary(expr, state, mod)
        case "bitand":
            return _partially_apply_binary(expr, state, and_)
        case "bitor":
            return _partially_apply_binary(expr, state, or_)
        case "bitxor":
            return _partially_apply_binary(expr, state, xor)
        case "lshift":
            return _partially_apply_binary(expr, state, lshift)
        case "rshift":
            return _partially_apply_binary(expr, state, rshift)
        case "eq":
            return _partially_apply_binary(expr, state, eq)
        case "ne":
            return _partially_apply_binary(expr, state, ne)
        case "lt":
            return _partially_apply_binary(expr, state, lt)
        case "le":
            return _partially_apply_binary(expr, state, le)
        case "gt":
            return _partially_apply_binary(expr, state, gt)
        case "ge":
            return _partially_apply_binary(expr, state, ge)
        case _:
            raise ValueError(f"Unsupported symbolic expression kind during preparation: {expr.kind}")


def _partially_apply_unary(
    expr: SymExpr,
    state: ValueLike | None,
    operator,
) -> ValueLike:
    arg = partially_prepare_value(expr.args[0], state)
    if _is_concrete(arg):
        return operator(arg)
    return SymExpr(expr.kind, args=(_exprify(arg),))


def _partially_apply_binary(
    expr: SymExpr,
    state: ValueLike | None,
    operator,
) -> ValueLike:
    left = partially_prepare_value(expr.args[0], state)
    right = partially_prepare_value(expr.args[1], state)
    if _is_concrete(left) and _is_concrete(right):
        return operator(left, right)
    return SymExpr(expr.kind, args=(_exprify(left), _exprify(right)))


def _get_item(base: ValueLike, key: int | str) -> ValueLike:
    if isinstance(base, Mapping):
        return base[key]
    if isinstance(base, Sequence) and not isinstance(base, str | bytes):
        return getitem(base, key)
    return getattr(base, str(key))
