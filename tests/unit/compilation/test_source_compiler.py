from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from catseq.compilation import CatSeqCompileError, compile_entry
from catseq.compilation.types import OASMAddress, OASMFunction


class _Experiment:
    duration = 0.35

    def build_sequence(self, params):
        raise AssertionError("compile_entry must not execute Python sequence code")


def _response() -> dict[str, object]:
    return {
        "schema_version": 1,
        "stage": "oasm_call_plan",
        "entry": "_Experiment.build_sequence",
        "oasm_call_plan": {
            "schema_version": 1,
            "epochs": [
                {
                    "id": 0,
                    "origin_cycles": 0,
                    "boards": [
                        {
                            "address": "rwg0",
                            "calls": [
                                {
                                    "offset_cycles": 0,
                                    "function": "wait",
                                    "args": [250],
                                }
                            ],
                        }
                    ],
                }
            ],
        },
        "logical_duration_cycles": 87500,
        "clock_hz": 250000000,
        "native_compile_seconds": 0.001,
        "diagnostics": [],
        "incremental": {"executed": 1, "green": 0, "red": 1},
    }


def test_compile_entry_compiles_source_without_executing_the_bound_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        bindings_path = Path(command[command.index("--link-bindings") + 1])
        target_path = Path(command[command.index("--target-profile") + 1])
        captured["bindings"] = json.loads(bindings_path.read_text())
        captured["target"] = json.loads(target_path.read_text())
        return subprocess.CompletedProcess(command, 0, json.dumps(_response()), "")

    monkeypatch.setattr("catseq.compilation.native.subprocess.run", fake_run)
    experiment = _Experiment()
    result = compile_entry(
        experiment.build_sequence,
        {"pulse_time_us": 0.35},
        environment={"schema_version": 1, "channels": {}},
        source_root=Path(__file__).parents[3],
        compiler="catseqc-test",
    )

    command = captured["command"]
    assert command[:2] == ["catseqc-test", "compile"]
    assert command[command.index("--entry") + 1] == "_Experiment.build_sequence"
    bindings = captured["bindings"]
    assert bindings["runtime_values"]["self.duration"] == 0.35
    assert bindings["runtime_values"]['params["pulse_time_us"]'] == 0.35
    assert captured["target"]["clock_hz"] == 250000000
    assert captured["target"]["rtmq_abi_version"] == 2
    assert result.logical_duration_cycles == 87500
    assert result.total_duration_us == pytest.approx(350.0)


def test_compile_result_converts_the_native_plan_to_oasm_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "catseq.compilation.native.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, json.dumps(_response()), ""
        ),
    )
    result = compile_entry(
        _Experiment().build_sequence,
        {},
        environment={"schema_version": 1, "channels": {}},
        source_root=Path(__file__).parents[3],
        compiler="catseqc-test",
    )

    calls = result.to_oasm_calls()
    assert calls[OASMAddress.RWG0][0].dsl_func is OASMFunction.WAIT
    assert calls[OASMAddress.RWG0][0].args == (250,)


def test_compile_entry_reports_native_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "catseq.compilation.native.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, "", "unsupported source expression"
        ),
    )

    with pytest.raises(CatSeqCompileError, match="unsupported source expression"):
        compile_entry(
            _Experiment().build_sequence,
            {},
            environment={"schema_version": 1, "channels": {}},
            source_root=Path(__file__).parents[3],
            compiler="catseqc-test",
        )
