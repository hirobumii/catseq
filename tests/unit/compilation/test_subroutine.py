"""
Unit tests for the RTMQ subroutine compiler facade.
"""

from __future__ import annotations

import pytest
from oasm.dev.rwg import C_RWG
from oasm.rtmq2 import DCH, R, asm, call, disassembler, function
from oasm.rtmq2 import core_domain as oasm_core_domain

from catseq.compilation.subroutine import clear_compiled_subroutines, compiled_subroutines
from catseq.control import core_domain, local


@pytest.fixture(autouse=True)
def reset_subroutine_registry():
    _reset_asm_state()
    yield
    _reset_asm_state()


def _reset_asm_state() -> None:
    clear_compiled_subroutines()
    asm.clear()
    asm.core = C_RWG
    asm.frame = (0,)
    asm.dat = 0


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


def test_core_domain_window_abi_uses_body_locals():
    @core_domain()
    def add_const(n, m):
        a: local = 5
        b: local = 1
        return n + m + a + b

    assert add_const._catseq_subroutine.abi == "window"
    add_const()

    assert _lines() == [
        "SUB - $22 $00 $22",
        "CSR - $23 LNK",
        "GLO - $24 5",
        "GLO - $25 1",
        "ADD - $FF $20 $21",
        "NOP -",
        "ADD - $FF $FF $24",
        "NOP -",
        "ADD - $20 $FF $25",
        "AMK - STK 3.0 $22",
        "AMK P PTR 2.0 $23",
    ]


def test_core_domain_window_abi_supports_augassign_on_locals():
    @core_domain()
    def bump(n):
        r: local = 0
        r = n
        r += 1
        return r

    assert bump._catseq_subroutine.abi == "window"
    bump()

    assert _lines() == [
        "SUB - $21 $00 $21",
        "CSR - $22 LNK",
        "ADD - $23 $00 $00",
        "ADD - $23 $00 $20",
        "NOP -",
        "ADD - $23 $23 1",
        "NOP -",
        "ADD - $20 $00 $23",
        "AMK - STK 3.0 $21",
        "AMK P PTR 2.0 $22",
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

    assert leaf_sum._catseq_subroutine.abi == "window"
    assert caller_sum._catseq_subroutine.abi == "window"

    leaf_sum()
    caller_sum()
    assert _lines() == [
        "SUB - $22 $00 $22",
        "CSR - $23 LNK",
        "GLO - $24 5",
        "ADD - $FF $20 $21",
        "NOP -",
        "ADD - $20 $FF $24",
        "AMK - STK 3.0 $22",
        "AMK P PTR 2.0 $23",
        "SUB - $22 $00 $22",
        "CSR - $23 LNK",
        "GLO - $27 5",
        "ADD - $25 $00 $20",
        "ADD - $26 $00 $21",
        "AMK - STK 3.0 $27",
        "CLO P PTR 0x000_00000",
        "ADD - $24 $00 $25",
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


def test_core_domain_matches_oasm_core_domain_for_issue9_fib_shape():
    @oasm_core_domain()
    def old_fib(n, r: 3):
        if n <= 2:
            return 1
        r = old_fib(n - 1)
        r += old_fib(n - 2)
        return r

    old_fib()
    function("_start", 2, 3)
    R[1] = call("old_fib", 10)
    old_lines = _lines()

    _reset_asm_state()

    @core_domain(recursion_bound=10)
    def new_fib(n):
        r: local
        if n <= 2:
            return 1
        r = new_fib(n - 1)
        r += new_fib(n - 2)
        return r

    new_fib()
    function("_start", 2, 3)
    R[1] = call("new_fib", 10)
    new_lines = _lines()

    assert new_lines == [line.replace("old_fib", "new_fib") for line in old_lines]


def test_core_domain_matches_oasm_core_domain_for_issue9_prime_shape():
    @oasm_core_domain()
    def old_prime(n, i: 3, j, m, r):
        sieve = DCH(1000)
        for i in range(n):
            sieve[i] = 1
        i = 2
        m = 4
        while m < n:
            if sieve[i] != 0:
                for j in range(m, n, i):
                    sieve[j] = 0
            i += 1
            m = i * i
        r = 0
        for i in range(2, n):
            if sieve[i] != 0:
                r += i
        return r

    old_prime()
    function("_start", 2, 3)
    R[1] = call("old_prime", 10)
    old_lines = _lines()

    _reset_asm_state()

    @core_domain(recursion_bound=10)
    def new_prime(n):
        i: local
        j: local
        m: local
        r: local
        sieve = DCH(1000)
        for i in range(n):
            sieve[i] = 1
        i = 2
        m = 4
        while m < n:
            if sieve[i] != 0:
                for j in range(m, n, i):
                    sieve[j] = 0
            i += 1
            m = i * i
        r = 0
        for i in range(2, n):
            if sieve[i] != 0:
                r += i
        return r

    new_prime()
    function("_start", 2, 3)
    R[1] = call("new_prime", 10)
    new_lines = _lines()

    assert new_lines == [line.replace("old_prime", "new_prime") for line in old_lines]


def test_core_domain_emits_callable_subroutine_flow():
    @core_domain()
    def add_const(n, m):
        a: local = 5
        b: local = 1
        return n + m + a + b

    call("__callable_flow_entry")
    add_const()
    function("__callable_flow_entry", 0, 0)
    R[0] = 0

    assert _lines() == [
        "GLO - $22 2",
        "NOP -",
        "AMK - STK 3.0 $22",
        "CLO P PTR 0x000_0000F",
        "SUB - $22 $00 $22",
        "CSR - $23 LNK",
        "GLO - $24 5",
        "GLO - $25 1",
        "ADD - $FF $20 $21",
        "NOP -",
        "ADD - $FF $FF $24",
        "NOP -",
        "ADD - $20 $FF $25",
        "AMK - STK 3.0 $22",
        "AMK P PTR 2.0 $23",
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
    assert registry["add_const"].abi == "window"


def test_core_domain_window_abi_remains_callable_from_raw_oasm_call():
    @core_domain()
    def add_const(n, m):
        a: local = 5
        return n + m + a

    add_const()
    function("__raw_call_entry", 0, 2)
    R[0] = call("add_const", 10, 20)

    assert _lines() == [
        "SUB - $22 $00 $22",
        "CSR - $23 LNK",
        "GLO - $24 5",
        "ADD - $FF $20 $21",
        "NOP -",
        "ADD - $20 $FF $24",
        "AMK - STK 3.0 $22",
        "AMK P PTR 2.0 $23",
        "SUB - $20 $00 $20",
        "CSR - $21 LNK",
        "GLO - $26 4",
        "GLO - $24 10",
        "GLO - $25 20",
        "AMK - STK 3.0 $26",
        "CLO P PTR 0x000_00000",
        "ADD - $20 $00 $24",
    ]


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
        "SUB - $21 $00 $21",
        "CSR - $22 LNK",
        "ADD - $23 $00 $00",
        "LST - $FE $00 $20",
        "GLO - $FF 5",
        "EQU - $FE $FE $00",
        "NOP -",
        "AMK P PTR $FE $FF",
        "GLO - $23 5",
        "GLO - $FF 2",
        "NOP -",
        "AMK P PTR 3.0 $FF",
        "GLO - $23 1",
        "NOP -",
        "ADD - $20 $00 $23",
        "AMK - STK 3.0 $21",
        "AMK P PTR 2.0 $22",
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
        "SUB - $21 $00 $21",
        "CSR - $22 LNK",
        "ADD - $23 $00 $20",
        "NOP -",
        "LST - $FE $00 $23",
        "GLO - $FF 5",
        "EQU - $FE $FE $00",
        "NOP -",
        "AMK P PTR $FE $FF",
        "SUB - $23 $23 1",
        "GLO - $FF -9",
        "NOP -",
        "AMK P PTR 3.0 $FF",
        "ADD - $20 $00 $23",
        "AMK - STK 3.0 $21",
        "AMK P PTR 2.0 $22",
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
        "SUB - $21 $00 $21",
        "CSR - $22 LNK",
        "ADD - $23 $00 $00",
        "ADD - $24 $00 $00",
        "ADD - $23 $00 $00",
        "NOP -",
        "LSE - $FE $20 $23",
        "GLO - $FF 6",
        "NOP -",
        "AMK P PTR $FE $FF",
        "ADD - $24 $24 $23",
        "ADD - $23 $23 1",
        "GLO - $FF -9",
        "NOP -",
        "AMK P PTR 3.0 $FF",
        "ADD - $20 $00 $24",
        "AMK - STK 3.0 $21",
        "AMK P PTR 2.0 $22",
    ]
