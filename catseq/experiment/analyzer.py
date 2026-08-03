"""Dependency-aware streaming and final experiment analysis."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
Request = Callable[[type], object | None]


@dataclass
class AnalyzerConfig:
    """Declarative analyzer configuration indexed from an experiment."""

    pass


@dataclass
class BaseAnalyzer:
    """A dependency-aware real-time and final analysis participant."""

    _dependencies_satisfied: bool = field(default=True, init=False, repr=False)

    @classmethod
    def dependent_analyzers(cls) -> tuple[type["BaseAnalyzer"], ...]:
        return ()

    def request_dependencies(self, request: Request) -> bool:
        del request
        return True

    def streaming_analyze(self, caller_name: str, order: int):
        del caller_name, order
        return None

    def analyze(self):
        return None


def _sort_analyzer_classes(
    required_analyzers: Iterable[type[BaseAnalyzer]],
) -> list[type[BaseAnalyzer]]:
    result: list[type[BaseAnalyzer]] = []
    visited: set[type[BaseAnalyzer]] = set()
    path: list[type[BaseAnalyzer]] = []

    def visit(analyzer: type[BaseAnalyzer]) -> None:
        if analyzer in visited:
            return
        if analyzer in path:
            cycle = path[path.index(analyzer) :] + [analyzer]
            raise ValueError(
                "analyzer dependency cycle: "
                + " -> ".join(item.__name__ for item in cycle)
            )
        path.append(analyzer)
        for dependency in analyzer.dependent_analyzers():
            visit(dependency)
        path.pop()
        visited.add(analyzer)
        result.append(analyzer)

    for analyzer in required_analyzers:
        visit(analyzer)
    return result


__all__ = ["AnalyzerConfig", "BaseAnalyzer"]
