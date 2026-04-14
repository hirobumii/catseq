"""
Public API for RTMQ subroutine compilation.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from functools import wraps

from .analysis import classify_subroutine, collect_named_calls
from .frontend import prepare_function_ast
from .ir import CompiledSubroutine
from .lower import lower_prepared_function


class _LocalSentinel:
    def __repr__(self) -> str:
        return "local"


local = _LocalSentinel()


_COMPILED_SUBROUTINES: dict[str, CompiledSubroutine] = {}


def compiled_subroutines() -> dict[str, CompiledSubroutine]:
    """Return the registered compiled subroutines."""

    return dict(_COMPILED_SUBROUTINES)


def clear_compiled_subroutines() -> None:
    """Clear the compiled subroutine registry."""

    _COMPILED_SUBROUTINES.clear()


def _parse_function_source(func) -> ast.Module:
    source_lines, _ = inspect.getsourcelines(func)
    source = textwrap.dedent("".join(source_lines))
    return ast.parse(source)


def core_domain(*, recursion_bound: int | None = None, dump: bool = False):
    """
    Compile a Python function into an RTMQ/OASM subroutine emitter.

    This frontend preserves the decorated Python surface while replacing the
    header slot-annotation hack with explicit body-local declarations.
    """

    def decorator(func):
        module = _parse_function_source(func)
        function_node = module.body[0]
        if not isinstance(function_node, ast.FunctionDef):
            raise ValueError("core_domain can only decorate a top-level function.")

        prepared_for_analysis = prepare_function_ast(module, abi="window")
        named_calls = collect_named_calls(function_node)
        classification = classify_subroutine(
            name=function_node.name,
            arg_count=len(prepared_for_analysis.arg_names),
            local_count=len(prepared_for_analysis.local_names),
            named_calls=named_calls,
            known_subroutines=set(_COMPILED_SUBROUTINES),
            recursion_bound=recursion_bound,
        )

        prepared = prepare_function_ast(module, abi=classification.abi)
        compiled = lower_prepared_function(
            prepared,
            abi=classification.abi,
            recursion_bound=recursion_bound,
            registry=_COMPILED_SUBROUTINES,
            original_func=func,
            dump=dump,
        )
        _COMPILED_SUBROUTINES[compiled.name] = compiled

        @wraps(func)
        def emitter():
            return compiled.emitter()

        emitter._catseq_subroutine = compiled  # type: ignore[attr-defined]
        return emitter

    return decorator
