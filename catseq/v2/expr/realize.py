"""
Realization and canonicalization helpers for V2 symbolic values.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import is_dataclass
from typing import Mapping

from .core import SymExpr
from .types import ValueLike

type Realizer = Callable[[object, ValueLike, Mapping[str, object] | None], object]

_REALIZERS: dict[type[object], Realizer] = {}


def register_realizer(type_: type[object], realizer: Realizer) -> None:
    _REALIZERS[type_] = realizer


def realize_value(
    value: ValueLike,
    state: ValueLike,
    env: Mapping[str, object] | None = None,
) -> object:
    if isinstance(value, SymExpr):
        return value.resolve(state, env)
    if isinstance(value, tuple):
        return tuple(realize_value(item, state, env) for item in value)
    if isinstance(value, list):
        return [realize_value(item, state, env) for item in value]
    if isinstance(value, dict):
        return {key: realize_value(item, state, env) for key, item in value.items()}
    realizer = _REALIZERS.get(type(value))
    if realizer is not None:
        return realizer(value, state, env)
    if is_dataclass(value):
        fields = {
            key: realize_value(getattr(value, key), state, env)
            for key in value.__dataclass_fields__
        }
        return type(value)(**fields)
    return value
