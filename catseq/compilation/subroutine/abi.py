"""
ABI helpers for RTMQ subroutine compilation.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable

from oasm.rtmq2 import (
    Func as oasm_func,
    P,
    Return as oasm_return,
    R as window_r,
    amk,
    asm,
    call as oasm_call,
    clo,
    core_ctx,
    core_reg,
    core_regq,
    label,
)

from .ir import CompiledSubroutine


FIXED_ARG_BASE = 8
FIXED_LOCAL_BASE = 16
WINDOW_LOCAL_GAP = 2


def fixed_bindings(arg_names: tuple[str, ...], local_names: tuple[str, ...]) -> dict[str, object]:
    """Return the fixed low-TCS bindings for a small leaf subroutine."""

    fixed_r = core_reg(base=0)
    bindings: dict[str, object] = {}
    for index, name in enumerate(arg_names):
        bindings[name] = fixed_r[FIXED_ARG_BASE + index]
    for index, name in enumerate(local_names):
        bindings[name] = fixed_r[FIXED_LOCAL_BASE + index]
    return bindings


def window_bindings(arg_names: tuple[str, ...], local_names: tuple[str, ...]) -> dict[str, object]:
    """Return the stack-window bindings for a general RTMQ subroutine."""

    bindings: dict[str, object] = {}
    for index, name in enumerate(arg_names):
        bindings[name] = window_r[index]
    for index, name in enumerate(local_names):
        bindings[name] = window_r[len(arg_names) + WINDOW_LOCAL_GAP + index]
    return bindings


@contextmanager
def fixed_subroutine_func(name: str, _arg_count: int, _local_count: int):
    """
    Emit a fixed low-TCS leaf subroutine.

    Leaf subroutines rely on the caller-updated `LNK` CSR and therefore do not
    save/restore stack-window state.
    """

    old_frame = getattr(asm, "frame", (0,))
    asm.frame = (0,)
    try:
        label(name)
        yield None
    except Exception:
        raise
    else:
        core = asm.core
        with asm:
            asm.core = core
            return_ins = amk("ptr", "2.0", "lnk", P)
        if asm[-1] != return_ins:
            amk("ptr", "2.0", "lnk", P)
    finally:
        asm.frame = old_frame


@contextmanager
def window_subroutine_func(name: str, arg_count: int, local_count: int):
    """Emit a stack-window RTMQ subroutine using the standard OASM frame helpers."""

    try:
        with oasm_func(name, arg_count + 2, arg_count + 1 + local_count):
            yield None
    except Exception:
        raise


def fixed_return(*rets):
    """Return from a fixed-ABI subroutine with a single scalar result."""

    if len(rets) > 1:
        raise ValueError("Fixed ABI subroutines support only one return value.")
    if rets:
        fixed_r = core_reg(base=0)
        fixed_r[FIXED_ARG_BASE] = rets[0]
    amk("ptr", "2.0", "lnk", P)


def call_fixed(name: str, *args):
    """Call a fixed-ABI subroutine and read the result from the fixed return slot."""

    fixed_r = core_reg(base=0)
    for index, value in enumerate(args):
        fixed_r[FIXED_ARG_BASE + index] = value
    target = name if name.startswith("#") else f"#{name}"
    clo("ptr", target, P)
    return fixed_r[FIXED_ARG_BASE]


def make_ctx(
    *,
    abi: str,
    bindings: dict[str, object],
    call_dispatch: Callable[..., object],
    subroutine_func: Callable[..., object],
    dump: bool,
) -> tuple[dict[str, object], Callable[[str], bool]]:
    """Create the OASM domain context and register predicate for a compiled subroutine."""

    del dump  # kept in the signature so callers can thread it uniformly

    ctx = core_ctx().copy()
    ctx.update(bindings)
    ctx["_catseq_subroutine_func"] = subroutine_func
    ctx["Call"] = call_dispatch
    if abi == "fixed":
        ctx["Return"] = fixed_return
    regq_base = core_regq()

    def regq(symbol: str) -> bool:
        return symbol in bindings or regq_base(symbol)

    return ctx, regq


def make_call_dispatch(registry: dict[str, CompiledSubroutine]) -> Callable[..., object]:
    """Build a call dispatcher that chooses between fixed and window ABI callees."""

    def dispatch(name: str, *args):
        compiled = registry.get(name)
        if compiled is not None and compiled.abi == "fixed":
            return call_fixed(name, *args)
        return oasm_call(name, *args)

    return dispatch
