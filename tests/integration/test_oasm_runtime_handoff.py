"""Pure OASM assembly into the Rust-owned runtime handoff."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from catseq import _native
from catseq.compilation.execution import assemble_oasm_calls
from catseq.compilation.types import OASMAddress, OASMCall, OASMFunction
from oasm.dev.main import C_MAIN
from oasm.dev.rwg import C_RWG
from oasm.rtmq2 import assembler, nop, run_cfg
from oasm.rtmq2.intf import sim_intf


ROOT = Path(__file__).parents[2]
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "oasm_parity"
    / "v1"
    / "runtime"
    / "two_board_noop_download.json"
)


def test_oasm_calls_assemble_into_an_immutable_native_program() -> None:
    interface = sim_intf()
    interface.nod_adr = 21
    interface.loc_chn = 0
    sequence = assembler(
        run_cfg(interface, [2], chn=7),
        [("rwg0", C_RWG)],
    )

    def two_nops() -> None:
        nop(2)

    calls = {
        OASMAddress.RWG0: [
            OASMCall(
                adr=OASMAddress.RWG0,
                dsl_func=OASMFunction.USER_DEFINED_FUNC,
                args=(two_nops, (), {}),
            )
        ]
    }
    expected_words = [
        int(word, 16)
        for word in json.loads(FIXTURE.read_text())["ich_program"]["words"]
    ]

    first = assemble_oasm_calls(calls, sequence)
    first_words = first.boards[0].ich_words
    second = assemble_oasm_calls(calls, sequence)

    assert isinstance(first, _native.AssembledOASMProgram)
    assert first.schema_version == 1
    assert first.reply_node == 21
    assert first.reply_channel == 0
    assert first.boards[0].address == "rwg0"
    assert first.boards[0].exception_handler_word == 20
    assert first_words == expected_words
    assert second.boards[0].ich_words == expected_words
    assert first.boards[0].ich_words == first_words
    assert list(sequence.asm["rwg0"]) == [0x00D00000, 0x00D00000]


def test_mixed_board_contexts_are_finalized_in_isolation() -> None:
    interface = sim_intf()
    interface.nod_adr = 20
    interface.loc_chn = 3
    sequence = assembler(
        run_cfg(interface, [2, 5], chn=7),
        [("main", C_MAIN), ("rwg0", C_RWG)],
    )

    def one_nop() -> None:
        nop()

    def two_nops() -> None:
        nop(2)

    calls = {
        OASMAddress.MAIN: [
            OASMCall(
                adr=OASMAddress.MAIN,
                dsl_func=OASMFunction.USER_DEFINED_FUNC,
                args=(one_nop, (), {}),
            )
        ],
        OASMAddress.RWG0: [
            OASMCall(
                adr=OASMAddress.RWG0,
                dsl_func=OASMFunction.USER_DEFINED_FUNC,
                args=(two_nops, (), {}),
            )
        ],
    }

    program = assemble_oasm_calls(calls, sequence)

    assert [board.address for board in program.boards] == ["main", "rwg0"]
    assert [board.exception_handler_word for board in program.boards] == [19, 20]
    assert list(sequence.asm["main"]) == [0x00D00000]
    assert list(sequence.asm["rwg0"]) == [0x00D00000, 0x00D00000]


def test_assembly_rejects_empty_or_inconsistent_reply_contexts() -> None:
    interface = sim_intf()
    interface.nod_adr = 20
    interface.loc_chn = 3
    sequence = assembler(
        run_cfg(interface, [2, 5], chn=7),
        [("rwg0", C_RWG), ("rwg1", C_RWG)],
    )

    with pytest.raises(ValueError, match="empty"):
        assemble_oasm_calls({}, sequence)

    def one_nop() -> None:
        nop()

    calls = {
        address: [
            OASMCall(
                adr=address,
                dsl_func=OASMFunction.USER_DEFINED_FUNC,
                args=(one_nop, (), {}),
            )
        ]
        for address in (OASMAddress.RWG0, OASMAddress.RWG1)
    }
    other_interface = sim_intf()
    other_interface.nod_adr = 21
    other_interface.loc_chn = 3
    sequence.asm["rwg1"].intf = other_interface

    with pytest.raises(ValueError, match="same reply endpoint"):
        assemble_oasm_calls(calls, sequence)

    sequence.asm["rwg0"].intf = None
    with pytest.raises(ValueError, match="has no interface"):
        assemble_oasm_calls({OASMAddress.RWG0: calls[OASMAddress.RWG0]}, sequence)


def test_assembler_callback_errors_propagate_without_execution_fallback() -> None:
    interface = sim_intf()
    interface.nod_adr = 20
    interface.loc_chn = 0
    sequence = assembler(run_cfg(interface, [2], chn=0), [("rwg0", C_RWG)])

    def rejected_callback() -> None:
        raise LookupError("calibration missing")

    calls = {
        OASMAddress.RWG0: [
            OASMCall(
                adr=OASMAddress.RWG0,
                dsl_func=OASMFunction.USER_DEFINED_FUNC,
                args=(rejected_callback, (), {}),
            )
        ]
    }

    with pytest.raises(LookupError, match="calibration missing"):
        assemble_oasm_calls(calls, sequence)
