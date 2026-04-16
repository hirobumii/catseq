"""
Static analysis helpers for RTMQ subroutine compilation.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

@dataclass(frozen=True)
class SubroutineClassification:
    """Classification result for ABI selection and recursion policy."""

    abi: str
    calls_subroutines: bool
    is_recursive: bool


class _NamedCallCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        func_name = getattr(node.func, "id", None)
        if func_name is not None:
            self.calls.add(func_name)
        self.generic_visit(node)


def collect_named_calls(node: ast.FunctionDef) -> set[str]:
    """Return the set of directly named call targets in a function."""

    collector = _NamedCallCollector()
    collector.visit(node)
    return collector.calls


def classify_subroutine(
    *,
    name: str,
    arg_count: int,
    local_count: int,
    named_calls: set[str],
    known_subroutines: set[str],
    recursion_bound: int | None,
) -> SubroutineClassification:
    """
    Choose an ABI and enforce the current recursion policy.

    The current policy prioritizes compatibility with legacy OASM call sites:
    - all compiled subroutines use the standard OASM/window ABI
    - self-recursion is allowed only when an explicit recursion bound is provided
    """

    is_recursive = name in named_calls
    calls_subroutines = any(target in known_subroutines or target == name for target in named_calls)

    if is_recursive and recursion_bound is None:
        raise ValueError(
            f"Recursive subroutine '{name}' requires an explicit recursion_bound."
        )

    return SubroutineClassification(
        abi="window",
        calls_subroutines=calls_subroutines,
        is_recursive=is_recursive,
    )
