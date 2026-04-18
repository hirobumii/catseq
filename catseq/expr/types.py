"""
Shared typing helpers for the expression system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, Sequence, TypeAlias

if TYPE_CHECKING:
    from .core import Expr

ScalarLiteral: TypeAlias = int | float | bool | str | None
ExprOperand: TypeAlias = "Expr | ScalarLiteral"
AttrBase: TypeAlias = "Expr | Mapping[object, object] | Sequence[object] | object"
ItemKey: TypeAlias = int | str
