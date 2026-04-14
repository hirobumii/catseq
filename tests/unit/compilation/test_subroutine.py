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
    yield
    asm.clear()


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

    assembly_lines = disassembler(core=C_RWG)(asm[:])

    assert any("GLO - $10 5" in line for line in assembly_lines)
    assert any("GLO - $11 1" in line for line in assembly_lines)
    assert any("ADD - $08 $08 $09" in line or "ADD - $FF $08 $09" in line for line in assembly_lines)
    assert not any("STK" in line for line in assembly_lines)
    assert not any("CSR - $" in line and "LNK" in line for line in assembly_lines)
    assert assembly_lines[-1] == "AMK P PTR 2.0 LNK"


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
    assembly_lines = disassembler(core=C_RWG)(asm[:])

    assert any("STK" in line for line in assembly_lines)
    assert any("CLO P PTR" in line for line in assembly_lines)
    assert any("CSR - $23 LNK" in line for line in assembly_lines)
    assert any("AMK P PTR 2.0 $23" in line for line in assembly_lines)


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

    assembly_lines = disassembler(core=C_RWG)(asm[:])

    assert any("CLO P PTR" in line for line in assembly_lines[:4])
    assert any("AMK P PTR 2.0 LNK" in line for line in assembly_lines)


def test_core_domain_registers_compiled_subroutines():
    @core_domain()
    def add_const(n, m):
        a: local = 5
        return n + m + a

    registry = compiled_subroutines()
    assert "add_const" in registry
    assert registry["add_const"].name == "add_const"
    assert registry["add_const"].abi == "fixed"
