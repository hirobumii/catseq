"""
Unit tests for the RTMQ subroutine compiler facade.
"""

from __future__ import annotations

import pytest
from oasm.dev.rwg import C_RWG
from oasm.rtmq2 import R, asm, call, disassembler, function

from catseq.compilation.subroutine import clear_compiled_subroutines, compiled_subroutines
from catseq.control import core_domain, local


@pytest.fixture(autouse=True)
def reset_subroutine_registry():
    clear_compiled_subroutines()
    asm.clear()
    asm.core = C_RWG
    asm.frame = (0,)
    yield
    asm.clear()
    asm.frame = (0,)


def _lines() -> list[str]:
    return disassembler(core=C_RWG)(asm[:])


def test_core_domain_rejects_header_slot_annotations():
    with pytest.raises(ValueError, match="Header register annotations"):

        @core_domain()
        def bad_subroutine(n, a: 4):
            return n + a


def test_core_domain_rejects_unbounded_recursion():
    with pytest.raises(ValueError, match="recursion_bound"):

        @core_domain()
        def recursive_subroutine(n):
            return recursive_subroutine(n)


def test_core_domain_accepts_bounded_recursion():
    @core_domain(recursion_bound=3)
    def recursive_subroutine(n):
        return recursive_subroutine(n)

    compiled = recursive_subroutine._catseq_subroutine
    assert compiled.abi == "window"
    assert compiled.recursion_bound == 3

    recursive_subroutine()
    assembly_lines = disassembler(core=C_RWG)(asm[:])
    assert any("CSR - $22 LNK" in line or "CSR - $23 LNK" in line for line in assembly_lines)
    assert any("CLO P PTR" in line for line in assembly_lines)


def test_core_domain_rejects_default_arguments():
    with pytest.raises(ValueError, match="default-valued parameters"):

        @core_domain()
        def bad_subroutine(n=1):
            return n


def test_core_domain_rejects_varargs():
    with pytest.raises(ValueError, match="varargs/kwargs"):

        @core_domain()
        def bad_subroutine(*args):
            return 0


def test_core_domain_rejects_tuple_returns():
    with pytest.raises(ValueError, match="single scalar return value"):

        @core_domain()
        def bad_subroutine(n):
            return n, n


def test_core_domain_rejects_duplicate_local_declarations():
    with pytest.raises(ValueError, match="Duplicate local declaration 'tmp'"):

        @core_domain()
        def bad_subroutine(n):
            tmp: local
            tmp: local
            return n


def test_core_domain_rejects_argument_local_name_collision():
    with pytest.raises(ValueError, match="Duplicate local declaration 'n'"):

        @core_domain()
        def bad_subroutine(n):
            n: local
            return n


def test_core_domain_rejects_late_local_declarations():
    with pytest.raises(ValueError, match="must appear before executable statements"):

        @core_domain()
        def bad_subroutine(n):
            value = n
            tmp: local
            return value


def test_core_domain_rejects_nested_local_declarations():
    with pytest.raises(ValueError, match="Nested local declarations"):

        @core_domain()
        def bad_subroutine(n):
            if n:
                tmp: local
            return n


def test_core_domain_fixed_leaf_abi_uses_body_locals():
    @core_domain()
    def add_const(n, m):
        a: local = 5
        b: local = 1
        return n + m + a + b

    assert add_const._catseq_subroutine.abi == "fixed"
    add_const()

    assert _lines() == [
        "GLO - $10 5",
        "GLO - $11 1",
        "ADD - $FF $08 $09",
        "NOP -",
        "ADD - $FF $FF $10",
        "NOP -",
        "ADD - $08 $FF $11",
        "AMK P PTR 2.0 LNK",
    ]


def test_core_domain_fixed_leaf_abi_supports_augassign_on_locals():
    @core_domain()
    def bump(n):
        r: local = 0
        r = n
        r += 1
        return r

    assert bump._catseq_subroutine.abi == "fixed"
    bump()

    assert _lines() == [
        "ADD - $10 $00 $00",
        "ADD - $10 $00 $08",
        "NOP -",
        "ADD - $10 $10 1",
        "NOP -",
        "ADD - $08 $00 $10",
        "AMK P PTR 2.0 LNK",
    ]


def test_core_domain_window_abi_for_compiled_calls():
    @core_domain()
    def leaf_sum(n, m):
        a: local = 5
        return n + m + a

    @core_domain()
    def caller_sum(n, m):
        result: local
        result = leaf_sum(n, m)
        return result

    assert leaf_sum._catseq_subroutine.abi == "fixed"
    assert caller_sum._catseq_subroutine.abi == "window"

    leaf_sum()
    caller_sum()
    assert _lines() == [
        "GLO - $10 5",
        "ADD - $FF $08 $09",
        "NOP -",
        "ADD - $08 $FF $10",
        "AMK P PTR 2.0 LNK",
        "SUB - $22 $00 $22",
        "CSR - $23 LNK",
        "ADD - $08 $00 $20",
        "ADD - $09 $00 $21",
        "CLO P PTR 0x000_00000",
        "ADD - $24 $00 $08",
        "NOP -",
        "ADD - $20 $00 $24",
        "AMK - STK 3.0 $22",
        "AMK P PTR 2.0 $23",
    ]


def test_core_domain_window_abi_supports_recursive_local_augassign():
    @core_domain(recursion_bound=10)
    def fib(n):
        r: local = 0
        if n <= 2:
            return 1
        r = fib(n - 1)
        r += fib(n - 2)
        return r

    assert fib._catseq_subroutine.abi == "window"
    fib()

    assembly_lines = _lines()
    assert any("CLO P PTR" in line for line in assembly_lines)
    assert any("AMK P PTR 2.0" in line for line in assembly_lines)


def test_core_domain_emits_callable_subroutine_flow():
    @core_domain()
    def add_const(n, m):
        a: local = 5
        b: local = 1
        return n + m + a + b

    call("_start")
    add_const()
    function("_start", 0, 0)
    R[0] = 0

    assert _lines() == [
        "GLO - $22 2",
        "NOP -",
        "AMK - STK 3.0 $22",
        "CLO P PTR 0x000_0000C",
        "GLO - $10 5",
        "GLO - $11 1",
        "ADD - $FF $08 $09",
        "NOP -",
        "ADD - $FF $FF $10",
        "NOP -",
        "ADD - $08 $FF $11",
        "AMK P PTR 2.0 LNK",
        "SUB - $20 $00 $20",
        "CSR - $21 LNK",
        "ADD - $20 $00 $00",
    ]


def test_core_domain_registers_compiled_subroutines():
    @core_domain()
    def add_const(n, m):
        a: local = 5
        return n + m + a

    registry = compiled_subroutines()
    assert "add_const" in registry
    assert registry["add_const"].name == "add_const"
    assert registry["add_const"].abi == "fixed"


def test_core_domain_compiles_if_else_control_flow():
    @core_domain()
    def branchy(n):
        x: local = 0
        if n > 0:
            x = 5
        else:
            x = 1
        return x

    branchy()
    assert _lines() == [
        "ADD - $10 $00 $00",
        "LST - $FE $00 $08",
        "GLO - $FF 5",
        "EQU - $FE $FE $00",
        "NOP -",
        "AMK P PTR $FE $FF",
        "GLO - $10 5",
        "GLO - $FF 2",
        "NOP -",
        "AMK P PTR 3.0 $FF",
        "GLO - $10 1",
        "NOP -",
        "ADD - $08 $00 $10",
        "AMK P PTR 2.0 LNK",
    ]


def test_core_domain_compiles_while_control_flow():
    @core_domain()
    def countdown(n):
        x: local
        x = n
        while x > 0:
            x = x - 1
        return x

    countdown()
    assert _lines() == [
        "ADD - $10 $00 $08",
        "NOP -",
        "LST - $FE $00 $10",
        "GLO - $FF 5",
        "EQU - $FE $FE $00",
        "NOP -",
        "AMK P PTR $FE $FF",
        "SUB - $10 $10 1",
        "GLO - $FF -9",
        "NOP -",
        "AMK P PTR 3.0 $FF",
        "ADD - $08 $00 $10",
        "AMK P PTR 2.0 LNK",
    ]


def test_core_domain_compiles_for_range_control_flow():
    @core_domain()
    def loopy(n):
        i: local = 0
        acc: local = 0
        for i in range(n):
            acc = acc + i
        return acc

    loopy()
    assert _lines() == [
        "ADD - $10 $00 $00",
        "ADD - $11 $00 $00",
        "ADD - $10 $00 $00",
        "NOP -",
        "LSE - $FE $08 $10",
        "GLO - $FF 6",
        "NOP -",
        "AMK P PTR $FE $FF",
        "ADD - $11 $11 $10",
        "ADD - $10 $10 1",
        "GLO - $FF -9",
        "NOP -",
        "AMK P PTR 3.0 $FF",
        "ADD - $08 $00 $11",
        "AMK P PTR 2.0 LNK",
    ]
