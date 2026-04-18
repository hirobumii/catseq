"""
Resolution and concreteness helpers for CatSeq expressions and morphisms.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from typing import Mapping

from .core import Expr


def contains_expr(value: object) -> bool:
    if isinstance(value, Expr):
        return True
    if isinstance(value, tuple):
        return any(contains_expr(item) for item in value)
    if isinstance(value, list):
        return any(contains_expr(item) for item in value)
    if isinstance(value, dict):
        return any(contains_expr(item) for item in value.values())
    if is_dataclass(value):
        return any(contains_expr(getattr(value, field.name)) for field in fields(value))
    return False


def resolve_value(
    value: object,
    state: object,
    env: Mapping[str, object] | None = None,
) -> object:
    if isinstance(value, Expr):
        return value.resolve(state, env)
    if isinstance(value, tuple):
        return tuple(resolve_value(item, state, env) for item in value)
    if isinstance(value, list):
        return [resolve_value(item, state, env) for item in value]
    if isinstance(value, dict):
        return {key: resolve_value(item, state, env) for key, item in value.items()}
    if is_dataclass(value):
        resolved_fields = {
            field.name: resolve_value(getattr(value, field.name), state, env)
            for field in fields(value)
        }
        return type(value)(**resolved_fields)
    return value


def structurally_equal(left: object, right: object) -> bool:
    if isinstance(left, Expr) and isinstance(right, Expr):
        return (
            left.kind == right.kind
            and left.value == right.value
            and len(left.args) == len(right.args)
            and all(structurally_equal(a, b) for a, b in zip(left.args, right.args, strict=True))
        )
    if isinstance(left, Expr) or isinstance(right, Expr):
        return False
    return left == right


def _realize_atomic(op, env: Mapping[str, object] | None):
    start_state = resolve_value(op.start_state, op.start_state, env)
    end_state = resolve_value(op.end_state, start_state, env)
    duration_cycles = resolve_value(op.duration_cycles, start_state, env)
    return replace(
        op,
        start_state=start_state,
        end_state=end_state,
        duration_cycles=duration_cycles,
    )


def realize_morphism(morphism, env: Mapping[str, object] | None = None):
    from ..lanes import Lane
    from ..morphism import Morphism

    new_lanes = {}
    for channel, lane in morphism.lanes.items():
        new_lanes[channel] = Lane(tuple(_realize_atomic(op, env) for op in lane.operations))
    duration_cycles = resolve_value(morphism._duration_cycles, None, env)
    return Morphism(new_lanes, _duration_cycles=duration_cycles)
