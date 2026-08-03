"""Append-only parameter history for one experiment lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, TypeVar

from .params import ExpParam, ScanPoint


T = TypeVar("T")


class _ReadOnlyList(list[Any]):
    @staticmethod
    def _immutable(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise TypeError("ParaDict projections are read-only")

    __setitem__ = _immutable  # type: ignore[assignment]
    __delitem__ = _immutable  # type: ignore[assignment]
    __iadd__ = _immutable  # type: ignore[assignment]
    __imul__ = _immutable  # type: ignore[assignment]
    append = _immutable
    clear = _immutable
    extend = _immutable  # type: ignore[assignment]
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable


class ParaDict:
    """Column-oriented record of every attempted scan point."""

    def __init__(self) -> None:
        self._columns: dict[str, list[Any]] = {}
        self._params_by_name: dict[str, ExpParam[Any]] = {}
        self._coordinate_axes: tuple[str, ...] | None = None
        self._record_count = 0

    def __len__(self) -> int:
        return self._record_count

    @property
    def para_dict(self) -> Mapping[str, list[Any]]:
        return MappingProxyType(
            {name: _ReadOnlyList(values) for name, values in self._columns.items()}
        )

    @property
    def columns(self) -> Mapping[str, tuple[Any, ...]]:
        return MappingProxyType(
            {name: tuple(values) for name, values in self._columns.items()}
        )

    def append(self, point: ScanPoint) -> None:
        self.append_point(point)

    def record(self, point: ScanPoint) -> None:
        self.append_point(point)

    def append_point(self, point: ScanPoint) -> None:
        param_values = tuple(point.params.items())
        names = tuple(param.name for param, _ in param_values)
        if len(set(names)) != len(names):
            raise ValueError("one ScanPoint cannot contain duplicate parameter names")
        axes = tuple(point.coordinates)
        self._validate_shape(param_values, axes)

        if self._record_count == 0:
            for param, _ in param_values:
                self._params_by_name[param.name] = param
                self._columns[param.name] = []
            self._coordinate_axes = axes
            for axis in axes:
                self._columns[f"__coord__{axis}"] = []
            self._columns["__idx__"] = []

        for param, value in param_values:
            self._columns[param.name].append(value)
        for axis in axes:
            self._columns[f"__coord__{axis}"].append(point.coordinates[axis])
        self._columns["__idx__"].append(point.execution_index)
        self._record_count += 1

    def values(self, param: ExpParam[T]) -> tuple[T, ...]:
        return tuple(self._columns[self._registered_param_name(param)])  # type: ignore[return-value]

    def current(self, param: ExpParam[T]) -> T:
        values = self.values(param)
        if not values:
            raise LookupError(f"no values recorded for parameter {param.name!r}")
        return values[-1]

    def coordinate_values(self, axis: str) -> tuple[int, ...]:
        try:
            return tuple(self._columns[f"__coord__{axis}"])
        except KeyError as error:
            raise KeyError(f"unknown traversal coordinate axis {axis!r}") from error

    @property
    def execution_indexes(self) -> tuple[int, ...]:
        return tuple(self._columns.get("__idx__", ()))

    def _validate_shape(
        self,
        param_values: tuple[tuple[ExpParam[Any], Any], ...],
        axes: tuple[str, ...],
    ) -> None:
        if self._record_count == 0:
            return
        if {param.name for param, _ in param_values} != set(self._params_by_name):
            raise ValueError("all ParaDict points must contain the same parameters")
        for param, _ in param_values:
            if self._params_by_name[param.name] is not param:
                raise ValueError(
                    "all ParaDict points must use the same ExpParam declarations"
                )
        if axes != self._coordinate_axes:
            raise ValueError("all ParaDict points must contain the same coordinate axes")

    def _registered_param_name(self, param: ExpParam[Any]) -> str:
        try:
            registered = self._params_by_name[param.name]
        except KeyError as error:
            raise KeyError(f"parameter {param.name!r} has not been recorded") from error
        if registered is not param:
            raise KeyError(
                f"parameter declaration {param.name!r} is not the recorded declaration"
            )
        return param.name


__all__ = ["ParaDict"]
