"""Immutable parameter values used at the experiment scan boundary."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, getcontext, localcontext
from numbers import Integral, Real
from types import MappingProxyType
from typing import Any, Callable, Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True, eq=False, slots=True)
class ExpParam(Generic[T]):
    """A named parameter declaration whose identity is its mapping key."""

    name: str
    unit: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError("ExpParam.name must be a string")
        if not self.name:
            raise ValueError("ExpParam.name must not be empty")
        if self.name.startswith("__"):
            raise ValueError("ExpParam names beginning with '__' are reserved")
        if self.unit is not None and not isinstance(self.unit, str):
            raise TypeError("ExpParam.unit must be a string or None")


@dataclass(frozen=True, slots=True, init=False)
class ExpParams(Mapping[ExpParam[Any], Any]):
    """Immutable concrete values for one experiment point."""

    _values: Mapping[ExpParam[Any], Any]

    def __init__(
        self,
        values: Mapping[ExpParam[Any], Any]
        | Iterable[tuple[ExpParam[Any], Any]]
        | None = None,
    ) -> None:
        copied = dict(values.items() if isinstance(values, Mapping) else values or ())
        if not all(isinstance(param, ExpParam) for param in copied):
            raise TypeError("ExpParams keys must be ExpParam declarations")
        object.__setattr__(self, "_values", MappingProxyType(copied))

    @classmethod
    def empty(cls) -> "ExpParams":
        return cls()

    def __getitem__(self, param: ExpParam[T]) -> T:
        if not isinstance(param, ExpParam):
            raise TypeError("ExpParams must be indexed by an ExpParam declaration")
        return self._values[param]

    def __iter__(self) -> Iterator[ExpParam[Any]]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    @property
    def mapping(self) -> Mapping[ExpParam[Any], Any]:
        return self._values

    def with_value(self, param: ExpParam[T], value: T) -> "ExpParams":
        if not isinstance(param, ExpParam):
            raise TypeError("ExpParams keys must be ExpParam declarations")
        updated = dict(self._values)
        updated[param] = value
        return ExpParams(updated)


@dataclass(frozen=True, slots=True)
class ScanPoint:
    """One immutable point in a repeat and tensor-scan traversal."""

    params: ExpParams
    coordinates: Mapping[str, int]
    execution_index: int

    def __post_init__(self) -> None:
        if not isinstance(self.params, ExpParams):
            raise TypeError("ScanPoint.params must be ExpParams")
        if not isinstance(self.execution_index, int) or isinstance(
            self.execution_index, bool
        ):
            raise TypeError("ScanPoint.execution_index must be an integer")
        if self.execution_index < 0:
            raise ValueError("ScanPoint.execution_index must not be negative")
        copied: dict[str, int] = {}
        for axis, index in self.coordinates.items():
            if not isinstance(axis, str) or not axis:
                raise ValueError("ScanPoint coordinate axes must have non-empty names")
            if not isinstance(index, int) or isinstance(index, bool):
                raise TypeError("ScanPoint coordinate indexes must be integers")
            if index < 0:
                raise ValueError("ScanPoint coordinate indexes must not be negative")
            copied[axis] = index
        object.__setattr__(self, "coordinates", MappingProxyType(copied))

    @property
    def tensor_coordinates(self) -> Mapping[str, int]:
        return self.coordinates


def compile_scan_values(
    values: Iterable[T] | tuple[object, object, object],
) -> tuple[T, ...]:
    """Freeze explicit values or expand a closed numeric range tuple."""

    if isinstance(values, tuple) and len(values) == 3:
        return _compile_numeric_range(*values)  # type: ignore[return-value]
    if isinstance(values, (str, bytes)):
        raise TypeError("scan values must be an iterable of values, not text")
    try:
        return tuple(values)
    except TypeError as error:
        raise TypeError("scan values must be an iterable or a range tuple") from error


def _compile_numeric_range(
    start: object, end: object, step: object
) -> tuple[object, ...]:
    start_decimal = _as_decimal(start, "start")
    end_decimal = _as_decimal(end, "end")
    step_decimal = _as_decimal(step, "step")
    if step_decimal == 0:
        raise ValueError("scan range step must not be zero")
    if start_decimal < end_decimal and step_decimal < 0:
        raise ValueError("a negative step cannot reach an increasing range endpoint")
    if start_decimal > end_decimal and step_decimal > 0:
        raise ValueError("a positive step cannot reach a decreasing range endpoint")

    convert: Callable[[Decimal], object]
    if all(isinstance(value, Integral) and not isinstance(value, bool) for value in (start, end, step)):
        convert = int
    elif any(isinstance(value, Decimal) for value in (start, end, step)):
        convert = _identity
    else:
        convert = float

    precision = _range_precision(start_decimal, end_decimal, step_decimal)
    result: list[object] = []
    with localcontext() as context:
        context.prec = precision
        index = 0
        while True:
            current = start_decimal + step_decimal * index
            if step_decimal > 0 and current > end_decimal:
                break
            if step_decimal < 0 and current < end_decimal:
                break
            result.append(convert(current))
            index += 1
    return tuple(result)


def _as_decimal(value: object, role: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, Real)):
        raise TypeError(f"scan range {role} must be a finite real number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise TypeError(f"scan range {role} must be a finite real number") from error
    if not result.is_finite():
        raise ValueError(f"scan range {role} must be finite")
    return result


def _range_precision(*values: Decimal) -> int:
    significant_digits = max(len(value.as_tuple().digits) for value in values)
    largest_exponent = max(
        (abs(value.adjusted()) for value in values if value != 0), default=0
    )
    return max(getcontext().prec, significant_digits + largest_exponent + 8)


def _identity(value: object) -> object:
    return value


__all__ = [
    "ExpParam",
    "ExpParams",
    "ScanPoint",
    "compile_scan_values",
]
