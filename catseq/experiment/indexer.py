"""Type-based dependency lookup for experiment analysis."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import fields, is_dataclass
from typing import Any, TypeVar


T = TypeVar("T")


class Indexer:
    """Index an experiment object graph by exact class and MRO."""

    def __init__(self, root: Any) -> None:
        self._strict_index: dict[type, list[Any]] = defaultdict(list)
        self._mro_index: dict[type, list[Any]] = defaultdict(list)
        self._seen: set[int] = set()
        self._build_index(root)

    def request(self, target_type: type[T], strict: bool = True) -> list[T]:
        index = self._strict_index if strict else self._mro_index
        return list(index.get(target_type, ()))

    def request_one(self, target_type: type[T], strict: bool = True) -> T | None:
        result = self.request(target_type, strict=strict)
        if len(result) > 1:
            scope = "exact" if strict else "MRO"
            raise LookupError(
                f"ambiguous {scope} dependency {target_type.__name__}: "
                f"{len(result)} matches"
            )
        return result[0] if result else None

    def _build_index(self, node: Any) -> None:
        if node is None:
            return
        if isinstance(node, dict):
            for value in node.values():
                self._build_index(value)
            return
        if isinstance(node, (list, tuple, set)):
            for value in node:
                self._build_index(value)
            return
        if not isinstance(node, _experiment_types()) or id(node) in self._seen:
            return

        self._seen.add(id(node))
        self._strict_index[type(node)].append(node)
        for node_type in type(node).mro():
            if node_type is not object:
                self._mro_index[node_type].append(node)

        from .base_exp import BaseExp

        if isinstance(node, BaseExp):
            if type(node) is not BaseExp:
                self._strict_index[BaseExp].append(node)
            self._build_index(getattr(node, "para_dict", None))
            self._build_index(getattr(node, "gen", None))
            self._build_index(getattr(node, "_analyzer_pipeline", None))

        if is_dataclass(node):
            for item in fields(node):
                if not item.name.startswith("_"):
                    self._build_index(getattr(node, item.name))


def _experiment_types() -> tuple[type, ...]:
    from .analyzer import AnalyzerConfig, BaseAnalyzer
    from .descartes import DescartesGenerator
    from .device import BaseDevice, DeviceList
    from .para_dict import ParaDict
    from .result import BaseResult

    result: tuple[type, ...] = (
        AnalyzerConfig,
        BaseAnalyzer,
        BaseDevice,
        BaseResult,
        DescartesGenerator,
        DeviceList,
        ParaDict,
    )
    try:
        from .base_exp import BaseExp
    except ImportError:
        return result
    return (*result, BaseExp)


__all__ = ["Indexer"]
