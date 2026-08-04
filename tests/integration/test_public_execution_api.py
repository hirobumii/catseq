from __future__ import annotations

from pathlib import Path

import pytest

import catseq
from catseq import (
    CatSeqCompileError,
    CatSeqRuntimeError,
    Compiler,
    CompiledSequence,
    EthernetRuntime,
)
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, identity
from catseq.targets import rtmq_v2_profile
from catseq.time_utils import ms
from catseq.types import Board, Channel, ChannelType


rwg0 = Board("rwg0")
ttl0 = Channel(rwg0, local_id=0, channel_type=ChannelType.TTL)
SYNTHETIC_DESTINATION = "02:ca:75:ee:00:01"
SYNTHETIC_REPLY = (60_001, 31)
SYNTHETIC_BOARD_ROUTES = {"rwg0": 60_000}


def ttl_sequence() -> Morphism:
    return identity(0) >> {ttl0: pulse(500 * ms)}


class TestSystem:
    source_root = Path(__file__).parent
    channels = {"test_public_execution_api.ttl0": ttl0}


def unused_opaque_call() -> None:
    pass


class TestSystemWithOpaqueCall(TestSystem):
    opaque_calls = {"test.unused_opaque_call": unused_opaque_call}


def test_oasm_and_raw_transport_helpers_are_not_public_exports() -> None:
    for name in (
        "assemble_oasm_calls",
        "BoardEndpoint",
        "compile_entry",
        "execute_oasm_program",
        "LinuxRawEthernetRuntimeConfig",
        "OASMCall",
        "OASMCompileResult",
    ):
        assert not hasattr(catseq, name)
        assert not hasattr(catseq.compilation, name)


def test_system_compiler_returns_a_rust_owned_compiled_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CATSEQ_CACHE_DIR", str(tmp_path / "cache"))
    compiler = Compiler.from_system(TestSystem())

    compiled = compiler.compile(ttl_sequence)

    assert isinstance(compiled, CompiledSequence)
    assert type(compiled).__module__ == "catseq._native"
    assert compiled.entry == "ttl_sequence"
    assert compiled.logical_duration_cycles == 125_000_000
    assert compiled.clock_hz == 250_000_000
    assert compiled.total_duration_us == pytest.approx(500_000)
    assert compiled.oasm_call_plan["schema_version"] == 1
    with pytest.raises(AttributeError):
        compiled.clock_hz = 1


def test_compiled_sequence_retains_the_system_opaque_callable_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CATSEQ_CACHE_DIR", str(tmp_path / "cache"))

    compiled = Compiler.from_system(TestSystemWithOpaqueCall()).compile(
        ttl_sequence
    )

    assert compiled._opaque_callables == {
        "test.unused_opaque_call": unused_opaque_call
    }


def test_compiler_rejects_non_scalar_environment_values(tmp_path: Path) -> None:
    with pytest.raises(CatSeqCompileError, match="cannot decode environment values"):
        Compiler(
            source_root=Path(__file__).parent,
            channels={},
            environment_values={"calibration": [1, 2, 3]},
            cache_dir=tmp_path / "cache",
        )


def test_compiler_rejects_a_zero_target_clock_before_compilation(
    tmp_path: Path,
) -> None:
    target = rtmq_v2_profile()
    target["clock_hz"] = 0

    with pytest.raises(CatSeqCompileError, match="clock_hz must be greater than zero"):
        Compiler(
            source_root=tmp_path,
            channels={},
            target_profile=target,
        )


@pytest.mark.parametrize(
    ("configured", "normalized"),
    [(0, 1), (1, 1), (25, 25)],
)
def test_ethernet_runtime_exposes_its_normalized_timeout_margin(
    configured: int,
    normalized: int,
) -> None:
    runtime = EthernetRuntime(
        interface="catseq-no-such-interface",
        destination=SYNTHETIC_DESTINATION,
        reply=SYNTHETIC_REPLY,
        boards=SYNTHETIC_BOARD_ROUTES,
        timeout_margin_ms=configured,
    )

    assert runtime.timeout_margin_ms == normalized


def test_ethernet_runtime_encodes_before_entering_the_rust_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CATSEQ_CACHE_DIR", str(tmp_path / "cache"))
    compiled = Compiler.from_system(TestSystem()).compile(ttl_sequence)
    runtime = EthernetRuntime(
        interface="catseq-no-such-interface",
        destination=SYNTHETIC_DESTINATION,
        reply=SYNTHETIC_REPLY,
        boards=SYNTHETIC_BOARD_ROUTES,
        timeout_margin_ms=1,
    )

    with pytest.raises(CatSeqRuntimeError) as raised:
        runtime.run(compiled)

    assert raised.value.code == "transport_open_failed"
    assert raised.value.execution_certainty == "not_started"
