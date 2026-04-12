"""
Shared typing aliases for CatSeq V2.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from catseq.types.common import Channel, State

if TYPE_CHECKING:
    from .core import SymExpr
else:
    SymExpr = object

type ScalarValue = int | float | bool | str | None
type ItemKey = int | str
type AttrBase = SymExpr | State
type ExprOperand = SymExpr | State | ScalarValue
type ContainerValue = tuple[object, ...] | list[object] | dict[object, object]
type SymbolicValue = SymExpr
type ValueLike = State | ScalarValue | SymbolicValue | ContainerValue
type StartStateMap = dict[Channel, ValueLike]
type EndStateFactory = Callable[[ValueLike], ValueLike]
