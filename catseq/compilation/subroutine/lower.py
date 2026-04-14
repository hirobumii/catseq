"""
Lower prepared subroutines into executable OASM emitters.
"""

from __future__ import annotations

from oasm import domain

from .abi import (
    fixed_bindings,
    fixed_subroutine_func,
    make_call_dispatch,
    make_ctx,
    window_bindings,
    window_subroutine_func,
)
from .frontend import PreparedFunction
from .ir import CompiledSubroutine


def lower_prepared_function(
    prepared: PreparedFunction,
    *,
    abi: str,
    recursion_bound: int | None,
    registry: dict[str, CompiledSubroutine],
    original_func,
    dump: bool,
):
    """Create the executable OASM emitter for a prepared subroutine."""

    bindings = (
        fixed_bindings(prepared.arg_names, prepared.local_names)
        if abi == "fixed"
        else window_bindings(prepared.arg_names, prepared.local_names)
    )
    subroutine_func = fixed_subroutine_func if abi == "fixed" else window_subroutine_func
    call_dispatch = make_call_dispatch(registry)
    ctx, regq = make_ctx(
        abi=abi,
        bindings=bindings,
        call_dispatch=call_dispatch,
        subroutine_func=subroutine_func,
        dump=dump,
    )

    for compiled_name in registry:
        ctx[f"#{compiled_name}"] = True
    ctx[f"#{prepared.name}"] = True

    def transform(_module):
        return prepared.transformed_module

    emitter = domain(ctx, regq=regq, sub=transform, dump=dump)(original_func)
    return CompiledSubroutine(
        name=prepared.name,
        abi=abi,
        arg_count=len(prepared.arg_names),
        local_count=len(prepared.local_names),
        recursion_bound=recursion_bound,
        emitter=emitter,
    )
