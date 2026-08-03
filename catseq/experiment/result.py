"""Typed append-only data read from experiment devices."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, fields
from typing import Any, Self, TypeVar


def list_field():
    """Declare one list-valued result column."""

    return field(default_factory=list)


TResult = TypeVar("TResult", bound="BaseResult")


def create_result_field(result_class: type[TResult]):
    """Declare the accumulator owned by an input device."""

    return field(default_factory=result_class)


@dataclass
class BaseResult:
    """Typed column data accumulated after each device read."""

    _last_idx: int = field(default=0, init=False, repr=False)

    @classmethod
    def from_list_dict(cls: type[TResult], rows: list[dict[str, Any]]) -> TResult:
        if rows is None:
            raise RuntimeError("device read returned None")
        if not rows:
            return cls()

        result_fields = {
            item.name for item in fields(cls) if not item.name.startswith("_")
        }
        values: dict[str, list[Any]] = defaultdict(list)
        for row in rows:
            unexpected = set(row) - result_fields
            if unexpected:
                raise ValueError(
                    f"{cls.__name__} received undeclared result keys: "
                    f"{sorted(unexpected)}"
                )
            for name in result_fields:
                if name not in row:
                    raise ValueError(f"{cls.__name__} result is missing key {name!r}")
                values[name].append(row[name])
        return cls(**values)

    def __iadd__(self, other: Self) -> Self:
        if type(self) is not type(other):
            raise TypeError("device results can only append the same result type")
        self._last_idx = self.get_list_length()
        for item in fields(self):
            if item.name.startswith("_"):
                continue
            getattr(self, item.name).extend(getattr(other, item.name))
        return self

    def last_slice(self) -> slice:
        return slice(self._last_idx, self.get_list_length())

    def get_list_length(self) -> int:
        lengths = [
            len(getattr(self, item.name))
            for item in fields(self)
            if not item.name.startswith("_")
        ]
        if not lengths:
            return 0
        if len(set(lengths)) != 1:
            raise RuntimeError(
                f"{self.__class__.__name__} result fields have unequal lengths"
            )
        return lengths[0]


__all__ = ["BaseResult", "create_result_field", "list_field"]
