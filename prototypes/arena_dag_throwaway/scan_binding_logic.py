"""PROTOTYPE ONLY: parameter dependency extraction for an arena template."""

from __future__ import annotations

from dataclasses import fields, is_dataclass

from catseq.expr import Expr
from catseq.morphism.deferred import MorphismDef


def _expr_vars(value: object, seen: set[int]) -> set[str]:
    if isinstance(value, Expr):
        result = {str(value.value)} if value.kind == "var" else set()
        for argument in value.args:
            result.update(_expr_vars(argument, seen))
        return result

    value_id = id(value)
    if value_id in seen:
        return set()
    seen.add(value_id)

    if isinstance(value, MorphismDef):
        result = set()
        for generator in value._generators:
            result.update(_expr_vars(generator, seen))
        return result
    if callable(value):
        result = set()
        for default in getattr(value, "__defaults__", ()) or ():
            result.update(_expr_vars(default, seen))
        for default in (getattr(value, "__kwdefaults__", None) or {}).values():
            result.update(_expr_vars(default, seen))
        for cell in getattr(value, "__closure__", ()) or ():
            try:
                cell_value = cell.cell_contents
            except ValueError:
                continue
            result.update(_expr_vars(cell_value, seen))
        return result
    if isinstance(value, dict):
        result = set()
        for item in value.values():
            result.update(_expr_vars(item, seen))
        return result
    if isinstance(value, (tuple, list)):
        result = set()
        for item in value:
            result.update(_expr_vars(item, seen))
        return result
    if is_dataclass(value) and not isinstance(value, type):
        result = set()
        for field in fields(value):
            result.update(_expr_vars(getattr(value, field.name), seen))
        return result
    return set()


def node_parameter_dependencies(arena) -> tuple[frozenset[str], ...]:
    """Compute transitive parameter dependencies in NodeId order."""

    dependencies: list[frozenset[str]] = []
    for node_id, payload in enumerate(arena.payload):
        current = _expr_vars(payload, set())
        left = arena.left[node_id]
        right = arena.right[node_id]
        if left >= 0:
            current.update(dependencies[left])
        if right >= 0:
            current.update(dependencies[right])
        dependencies.append(frozenset(current))
    return tuple(dependencies)


def reverse_parameter_index(
    dependencies: tuple[frozenset[str], ...],
) -> dict[str, tuple[int, ...]]:
    result: dict[str, list[int]] = {}
    for node_id, parameters in enumerate(dependencies):
        for parameter in parameters:
            result.setdefault(parameter, []).append(node_id)
    return {parameter: tuple(nodes) for parameter, nodes in result.items()}
