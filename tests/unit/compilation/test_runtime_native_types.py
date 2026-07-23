import dataclasses

import pytest

from catseq import _native


def test_runtime_handoff_uses_frozen_native_classes() -> None:
    board = _native.AssembledOASMBoard(
        "main",
        [0x00D00000, 0x00E00000],
        1,
    )
    program = _native.AssembledOASMProgram(1, 20, 3, [board])
    endpoint = _native.BoardEndpoint("main", 2, 0, 1024)
    config = _native.LinuxRawEthernetRuntimeConfig(
        1,
        "enp1s0",
        None,
        2_000,
        [endpoint],
    )

    assert type(program).__module__ == "catseq._native"
    assert not hasattr(_native, "validate_runtime_handoff")
    assert not dataclasses.is_dataclass(program)
    assert program.schema_version == 1
    assert program.reply_node == 20
    assert program.reply_channel == 3
    assert program.boards[0].address == "main"
    assert program.boards[0].ich_words == [0x00D00000, 0x00E00000]
    assert program.boards[0].exception_handler_word == 1
    assert config.interface == "enp1s0"
    assert config.destination_mac is None
    assert config.timeout_ms == 2_000
    assert config.boards[0].node == 2
    assert config.boards[0].channel == 0
    with pytest.raises(AttributeError):
        program.reply_node = 21


def test_native_constructors_surface_rust_contract_errors() -> None:
    with pytest.raises(ValueError, match="unknown OASM board address"):
        _native.AssembledOASMBoard("rwg12", [0x00D00000], 0)

    with pytest.raises(ValueError, match="exceeds five bits"):
        _native.BoardEndpoint("main", 2, 32, 1024)
