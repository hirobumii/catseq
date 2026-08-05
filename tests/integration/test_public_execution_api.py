from __future__ import annotations

from pathlib import Path
from runpy import run_path

import pytest

import catseq
import blackbox_module_support as blackbox_helpers
from blackbox_module_support import (
    external_blackbox_sequence,
)
from catseq.compilation._oasm_encoder import encode_compiled_sequence
from catseq import (
    CatSeqCompileError,
    CatSeqRuntimeError,
    Compiler,
    CompiledSequence,
    EthernetRuntime,
)
from catseq.hardware.ttl import pulse, set_high, set_low
from catseq.morphism import Morphism, identity, repeat_morphism
from catseq.oasm import black_box
from catseq.targets import rtmq_v2_profile
from catseq.time_utils import Duration, cycles, ms
from catseq.types import Board, Channel, ChannelType
from oasm.rtmq2 import nop


rwg0 = Board("rwg0")
rwg1 = Board("rwg1")
ttl0 = Channel(rwg0, local_id=0, channel_type=ChannelType.TTL)
ttl1 = Channel(rwg1, local_id=1, channel_type=ChannelType.TTL)
SYNTHETIC_DESTINATION = "02:ca:75:ee:00:01"
SYNTHETIC_REPLY = (60_001, 31)
SYNTHETIC_BOARD_ROUTES = {"rwg0": 60_000}


def ttl_sequence() -> Morphism:
    return identity(0) >> {ttl0: pulse(500 * ms)}


def emit_raw_oasm() -> None:
    nop(n=12)


def emit_other_raw_oasm() -> None:
    nop(n=12)


def blackbox_sequence() -> Morphism:
    return black_box(
        duration_cycles=12,
        board_funcs={rwg0: emit_raw_oasm},
    )


def blackbox_with_removed_state_argument() -> Morphism:
    return black_box(
        duration_cycles=12,
        board_funcs={rwg0: emit_raw_oasm},
        channel_states={},  # type: ignore[call-arg]
    )


def multi_board_blackbox_sequence() -> Morphism:
    return black_box(
        duration_cycles=12,
        board_funcs={
            rwg0: emit_raw_oasm,
            rwg1: emit_other_raw_oasm,
        },
        user_args=(7,),
        user_kwargs={"label": "blackbox"},
    )


def adjacent_same_board_blackboxes_sequence() -> Morphism:
    return black_box(
        duration_cycles=12,
        board_funcs={rwg0: emit_raw_oasm},
    ) >> black_box(
        duration_cycles=12,
        board_funcs={rwg0: emit_other_raw_oasm},
    )


def overlapping_same_board_blackboxes_sequence() -> Morphism:
    return black_box(
        duration_cycles=12,
        board_funcs={rwg0: emit_raw_oasm},
    ) | (
        identity(cycles(6))
        >> black_box(
            duration_cycles=12,
            board_funcs={rwg0: emit_other_raw_oasm},
        )
    )


def zero_duration_blackbox_inside_another_sequence() -> Morphism:
    return black_box(
        duration_cycles=12,
        board_funcs={rwg0: emit_raw_oasm},
    ) | (
        identity(cycles(6))
        >> black_box(
            duration_cycles=0,
            board_funcs={rwg0: emit_other_raw_oasm},
        )
    )


def repeated_blackbox_sequence() -> Morphism:
    return repeat_morphism(blackbox_sequence(), 3)


def multi_board_blackbox_with_followup_sequence() -> Morphism:
    return (
        multi_board_blackbox_sequence()
        >> identity(cycles(1))
        >> {
            ttl0: set_high(),
            ttl1: set_high(),
        }
    )


def imported_module_blackbox_sequence() -> Morphism:
    return external_blackbox_sequence()


def module_qualified_callback_blackbox_sequence() -> Morphism:
    return black_box(
        duration_cycles=12,
        board_funcs={
            rwg0: blackbox_helpers.emit_external_raw_oasm,
        },
    )


def blackbox_with_inner_board_event() -> Morphism:
    return blackbox_sequence() | (
        identity(cycles(6)) >> {ttl0: set_high()}
    )


def blackbox_with_start_board_event() -> Morphism:
    return blackbox_sequence() | {ttl0: set_high()}


def blackbox_with_end_board_event() -> Morphism:
    return blackbox_sequence() | (
        identity(cycles(12)) >> {ttl0: set_high()}
    )


class TestSystem:
    source_root = Path(__file__).parent
    channels = {"test_public_execution_api.ttl0": ttl0}


class BlackBoxSystem:
    source_root = Path(__file__).parent
    channels = {
        "test_public_execution_api.ttl0": ttl0,
        "test_public_execution_api.ttl1": ttl1,
    }


def unused_opaque_call() -> None:
    pass


class TestSystemWithOpaqueCall(TestSystem):
    opaque_calls = {"test.unused_opaque_call": unused_opaque_call}


class EnvironmentRewindExperiment:
    rewind: Duration

    def sequence(self) -> Morphism:
        return (
            identity(cycles(2))
            >> {ttl0: set_high()}
            >> identity(self.rewind)
            >> {ttl0: set_low()}
        )


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


def test_source_blackbox_compiles_to_the_existing_oasm_callback_handoff(
    tmp_path: Path,
) -> None:
    compiled = Compiler(
        source_root=BlackBoxSystem.source_root,
        channels=BlackBoxSystem.channels,
        cache_dir=tmp_path / "cache",
    ).compile(blackbox_sequence)

    assert compiled.logical_duration_cycles == 12
    assert compiled._opaque_callables == {
        "test_public_execution_api.emit_raw_oasm": emit_raw_oasm,
    }
    assert compiled.oasm_call_plan["epochs"][0]["boards"] == [
        {
            "address": "rwg0",
            "calls": [
                {
                    "offset_cycles": 0,
                    "function": "user_defined_func",
                    "args": [
                        "test_public_execution_api.emit_raw_oasm",
                        [],
                        {},
                    ],
                },
            ],
        }
    ]
    assembled = encode_compiled_sequence(compiled, reply=SYNTHETIC_REPLY)
    assert assembled.boards[0].address == "rwg0"
    assert assembled.boards[0].exception_handler_word > 0


def test_source_blackbox_rejects_the_removed_channel_states_argument(
    tmp_path: Path,
) -> None:
    compiler = Compiler(
        source_root=BlackBoxSystem.source_root,
        channels=BlackBoxSystem.channels,
        cache_dir=tmp_path / "cache",
    )

    with pytest.raises(
        CatSeqCompileError,
        match='unexpected keyword argument "channel_states"',
    ):
        compiler.compile(blackbox_with_removed_state_argument)


def test_source_blackbox_keeps_multi_board_timing_and_arguments_shared(
    tmp_path: Path,
) -> None:
    compiled = Compiler(
        source_root=BlackBoxSystem.source_root,
        channels=BlackBoxSystem.channels,
        cache_dir=tmp_path / "cache",
    ).compile(multi_board_blackbox_sequence)

    assert compiled.logical_duration_cycles == 12
    boards = compiled.oasm_call_plan["epochs"][0]["boards"]
    assert [board["address"] for board in boards] == ["rwg0", "rwg1"]
    assert [board["calls"][0]["offset_cycles"] for board in boards] == [0, 0]
    assert [len(board["calls"]) for board in boards] == [1, 1]
    assert [board["calls"][0]["args"][1:] for board in boards] == [
        [[7], {"label": "blackbox"}],
        [[7], {"label": "blackbox"}],
    ]
    assert compiled._opaque_callables == {
        "test_public_execution_api.emit_other_raw_oasm": emit_other_raw_oasm,
        "test_public_execution_api.emit_raw_oasm": emit_raw_oasm,
    }


def test_source_blackbox_allows_adjacent_same_board_regions(
    tmp_path: Path,
) -> None:
    compiled = Compiler(
        source_root=BlackBoxSystem.source_root,
        channels=BlackBoxSystem.channels,
        cache_dir=tmp_path / "cache",
    ).compile(adjacent_same_board_blackboxes_sequence)

    assert compiled.logical_duration_cycles == 24
    calls = compiled.oasm_call_plan["epochs"][0]["boards"][0]["calls"]
    assert [call["offset_cycles"] for call in calls] == [0, 12]
    assert [call["function"] for call in calls] == [
        "user_defined_func",
        "user_defined_func",
    ]
    assert [call["args"][0] for call in calls] == [
        "test_public_execution_api.emit_raw_oasm",
        "test_public_execution_api.emit_other_raw_oasm",
    ]


def test_source_blackbox_rejects_overlapping_same_board_regions(
    tmp_path: Path,
) -> None:
    compiler = Compiler(
        source_root=BlackBoxSystem.source_root,
        channels=BlackBoxSystem.channels,
        cache_dir=tmp_path / "cache",
    )

    with pytest.raises(
        CatSeqCompileError,
        match="conflicts with another blackbox operation",
    ):
        compiler.compile(overlapping_same_board_blackboxes_sequence)


def test_source_blackbox_treats_zero_duration_regions_as_empty(
    tmp_path: Path,
) -> None:
    compiled = Compiler(
        source_root=BlackBoxSystem.source_root,
        channels=BlackBoxSystem.channels,
        cache_dir=tmp_path / "cache",
    ).compile(zero_duration_blackbox_inside_another_sequence)

    assert compiled.logical_duration_cycles == 12
    calls = compiled.oasm_call_plan["epochs"][0]["boards"][0]["calls"]
    assert [call["args"][0] for call in calls] == [
        "test_public_execution_api.emit_raw_oasm",
        "test_public_execution_api.emit_other_raw_oasm",
    ]


def test_source_blackbox_composes_as_the_final_hardware_loop_operation(
    tmp_path: Path,
) -> None:
    compiled = Compiler(
        source_root=BlackBoxSystem.source_root,
        channels=BlackBoxSystem.channels,
        cache_dir=tmp_path / "cache",
    ).compile(repeated_blackbox_sequence)

    assert compiled.logical_duration_cycles == 36
    calls = compiled.oasm_call_plan["epochs"][0]["boards"][0]["calls"]
    assert [call["function"] for call in calls] == [
        "loop_begin",
        "user_defined_func",
        "loop_end",
    ]
    assert [call["offset_cycles"] for call in calls] == [0, 0, 12]


def test_source_blackbox_occupies_the_declared_duration_on_every_board(
    tmp_path: Path,
) -> None:
    compiled = Compiler(
        source_root=BlackBoxSystem.source_root,
        channels=BlackBoxSystem.channels,
        cache_dir=tmp_path / "cache",
    ).compile(multi_board_blackbox_with_followup_sequence)

    assert compiled.logical_duration_cycles == 13
    boards = compiled.oasm_call_plan["epochs"][0]["boards"]
    for board in boards:
        assert board["calls"][0]["function"] == "user_defined_func"
        assert board["calls"][1] == {
            "offset_cycles": 12,
            "function": "wait",
            "args": [1],
        }
        assert board["calls"][2]["offset_cycles"] == 13
        assert board["calls"][2]["function"] == "ttl_set"


def test_source_blackbox_resolves_a_callback_from_an_imported_source_module(
    tmp_path: Path,
) -> None:
    compiled = Compiler(
        source_root=BlackBoxSystem.source_root,
        channels=BlackBoxSystem.channels,
        cache_dir=tmp_path / "cache",
    ).compile(imported_module_blackbox_sequence)

    assert compiled._opaque_callables == {
        "blackbox_module_support.emit_external_raw_oasm": (
            blackbox_helpers.emit_external_raw_oasm
        ),
    }


def test_source_blackbox_resolves_a_module_qualified_callback(
    tmp_path: Path,
) -> None:
    compiled = Compiler(
        source_root=BlackBoxSystem.source_root,
        channels=BlackBoxSystem.channels,
        cache_dir=tmp_path / "cache",
    ).compile(module_qualified_callback_blackbox_sequence)

    assert compiled._opaque_callables == {
        "blackbox_module_support.emit_external_raw_oasm": (
            blackbox_helpers.emit_external_raw_oasm
        ),
    }
    call = compiled.oasm_call_plan["epochs"][0]["boards"][0]["calls"][0]
    assert call["args"][0] == "blackbox_module_support.emit_external_raw_oasm"


def test_source_blackbox_normalizes_main_module_callback_identity(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "main_blackbox.py"
    source_path.write_text(
        "from catseq.morphism import Morphism\n"
        "from catseq.oasm import black_box\n"
        "from catseq.types import Board\n"
        "from oasm.rtmq2 import nop\n\n"
        "board = Board('rwg0')\n\n"
        "def emit_raw_oasm() -> None:\n"
        "    nop(n=12)\n\n"
        "def sequence() -> Morphism:\n"
        "    return black_box(\n"
        "        duration_cycles=12,\n"
        "        board_funcs={board: emit_raw_oasm},\n"
        "    )\n"
    )
    main_scope = run_path(str(source_path), run_name="__main__")

    compiled = Compiler(
        source_root=tmp_path,
        channels={},
        cache_dir=tmp_path / "cache",
    ).compile(main_scope["sequence"])

    assert compiled._opaque_callables == {
        "main_blackbox.emit_raw_oasm": main_scope["emit_raw_oasm"],
    }
    call = compiled.oasm_call_plan["epochs"][0]["boards"][0]["calls"][0]
    assert call["args"][0] == "main_blackbox.emit_raw_oasm"


def test_source_blackbox_rejects_same_board_events_inside(
    tmp_path: Path,
) -> None:
    compiler = Compiler(
        source_root=BlackBoxSystem.source_root,
        channels=BlackBoxSystem.channels,
        cache_dir=tmp_path / "cache",
    )

    with pytest.raises(
        CatSeqCompileError,
        match="conflicts with a blackbox operation on board rwg0",
    ):
        compiler.compile(blackbox_with_inner_board_event)


def test_source_blackbox_allows_same_board_events_at_both_boundaries(
    tmp_path: Path,
) -> None:
    compiler = Compiler(
        source_root=BlackBoxSystem.source_root,
        channels=BlackBoxSystem.channels,
        cache_dir=tmp_path / "cache",
    )

    start_compiled = compiler.compile(blackbox_with_start_board_event)
    end_compiled = compiler.compile(blackbox_with_end_board_event)

    assert start_compiled.logical_duration_cycles == 12
    assert end_compiled.logical_duration_cycles == 12
    end_calls = end_compiled.oasm_call_plan["epochs"][0]["boards"][0]["calls"]
    assert end_calls[-1]["offset_cycles"] == 12
    assert end_calls[-1]["function"] == "ttl_set"


def test_compiler_rejects_non_scalar_environment_values(tmp_path: Path) -> None:
    with pytest.raises(CatSeqCompileError, match="cannot decode environment values"):
        Compiler(
            source_root=Path(__file__).parent,
            channels={},
            environment_values={"calibration": [1, 2, 3]},
            cache_dir=tmp_path / "cache",
        )


def test_public_environment_duration_can_rewind_the_timeline(tmp_path: Path) -> None:
    compiled = Compiler(
        source_root=Path(__file__).parent,
        channels={"test_public_execution_api.ttl0": ttl0},
        environment_values={
            "test_public_execution_api.EnvironmentRewindExperiment.rewind": -1
        },
        cache_dir=tmp_path / "cache",
    ).compile(EnvironmentRewindExperiment().sequence)

    assert compiled.logical_duration_cycles == 2
    calls = compiled.oasm_call_plan["epochs"][0]["boards"][0]["calls"]
    assert calls == [
        {"offset_cycles": 0, "function": "wait", "args": [1]},
        {"offset_cycles": 1, "function": "ttl_set", "args": [1, 0, "rwg"]},
        {"offset_cycles": 2, "function": "ttl_set", "args": [1, 1, "rwg"]},
    ]


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
