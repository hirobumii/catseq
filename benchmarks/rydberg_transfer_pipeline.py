#!/usr/bin/env python3
"""Benchmark the CatSeq 0.3.1 Rydberg-transfer pipeline without device I/O.

The workload is the static source bundle owned by ``rb1-next``.  This script
never imports the experiment package and deliberately uses a nonexistent
interface for the final Rust stage, after loader and RTLink materialization.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from types import ModuleType
from typing import Any, Callable

from catseq import _native
from catseq.compilation import (
    BoardEndpoint,
    CatSeqRuntimeError,
    LinuxRawEthernetRuntimeConfig,
    assemble_oasm_calls,
    execute_oasm_program,
    oasm_call_plan_to_calls,
)
from oasm.dev.main import C_MAIN, run_cfg
from oasm.dev.rsp import C_RSP
from oasm.dev.rwg import C_RWG
from oasm.rtmq2 import assembler
from oasm.rtmq2.intf import sim_intf


CATSEQ_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RB1_ROOT = CATSEQ_ROOT.parent / "rb1-next"
TARGET_PROFILE = CATSEQ_ROOT / "catseq" / "targets" / "rtmq_v2.toml"
NONEXISTENT_INTERFACE = "catseq-benchmark-no-device"
LINUX_INTERFACE_NAME_MAX_BYTES = 15
CHASSIS2_MAC = [0x60, 0xCF, 0x84, 0xA7, 0xBC, 0x01]
CHASSIS2_HOST_NODE = 21
CORE_BY_KIND = {"main": C_MAIN, "rsp": C_RSP, "rwg": C_RWG}
EXPECTED_RUNTIME_PROGRAM_SHA256 = (
    "96e4efce1ccc28ec10c137d5c9ed9e2d76f4d214a9860ac658c7d9d46b82aac1"
)


def _load_verifier(rb1_root: Path) -> ModuleType:
    path = rb1_root / "tools" / "verify_catseq_native_compiler.py"
    specification = importlib.util.spec_from_file_location(
        "_catseq_rydberg_verifier",
        path,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load Rydberg verifier at {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _measure(
    callback: Callable[[], Any],
    *,
    samples: int,
    warmup: int = 0,
) -> tuple[list[float], Any]:
    result: Any = None
    for _ in range(warmup):
        result = callback()
    timings = []
    for _ in range(samples):
        gc.collect()
        started = time.perf_counter_ns()
        result = callback()
        timings.append((time.perf_counter_ns() - started) / 1_000_000)
    return timings, result


def _summary(samples: list[float]) -> dict[str, float | int]:
    ordered = sorted(samples)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "samples": len(samples),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(ordered[p95_index], 3),
        "min_ms": round(ordered[0], 3),
        "max_ms": round(ordered[-1], 3),
    }


def _compile_payload(request: dict[str, Any]) -> bytes:
    return json.dumps(request, separators=(",", ":")).encode()


def _active_board_cores(
    request: dict[str, Any],
    response: dict[str, Any],
) -> list[tuple[str, Any]]:
    active_boards = {
        board["address"]
        for epoch in response["oasm_call_plan"]["epochs"]
        for board in epoch["boards"]
    }
    cores = [
        (address, CORE_BY_KIND[board["kind"]])
        for address, board in request["target_profile"]["boards"].items()
        if address in active_boards
    ]
    if {address for address, _core in cores} != active_boards:
        raise RuntimeError("target profile does not cover every active board")
    return cores


def _physical_node(address: str) -> int:
    if address == "main":
        return 0
    if address.startswith(("rwg", "rsp")):
        return int(address[3:]) + 1
    raise ValueError(f"no physical-node convention for {address!r}")


def _new_assembler(board_cores: list[tuple[str, Any]]) -> Any:
    interface = sim_intf()
    interface.nod_adr = CHASSIS2_HOST_NODE
    interface.loc_chn = 0
    nodes = sorted(_physical_node(address) for address, _core in board_cores)
    return assembler(run_cfg(interface, nodes), board_cores)


def _opaque_stub(*_args: Any, **_kwargs: Any) -> None:
    """Represent an already-accounted-for opaque operation without device I/O."""


def _opaque_callables(request: dict[str, Any]) -> dict[str, Callable[..., None]]:
    return {
        binding["callable"]: _opaque_stub
        for binding in request["compile_environment"]["opaque_calls"].values()
    }


def _runtime_config(program: Any) -> Any:
    if sys.platform != "linux":
        raise RuntimeError("the raw-Ethernet preparation benchmark requires Linux")
    if len(NONEXISTENT_INTERFACE.encode()) <= LINUX_INTERFACE_NAME_MAX_BYTES:
        raise RuntimeError(
            "offline benchmark interface must exceed the Linux interface-name limit"
        )
    endpoints = [
        BoardEndpoint(
            board.address,
            _physical_node(board.address),
            0,
            131_072,
        )
        for board in program.boards
    ]
    return LinuxRawEthernetRuntimeConfig(
        1,
        NONEXISTENT_INTERFACE,
        CHASSIS2_MAC,
        5_000,
        endpoints,
    )


def _prepare_until_open_failure(program: Any, config: Any) -> None:
    try:
        execute_oasm_program(program, config)
    except CatSeqRuntimeError as error:
        if error.code != "transport_open_failed":
            raise
        if set(error.board_evidence.values()) != {"not_dispatched"}:
            raise RuntimeError(
                "offline runtime benchmark advanced execution evidence"
            ) from error
        return
    raise RuntimeError("nonexistent benchmark interface unexpectedly opened")


def _program_fingerprint(program: Any) -> tuple[str, dict[str, int]]:
    boards = [
        {
            "address": board.address,
            "exception_handler_word": board.exception_handler_word,
            "ich_words": list(board.ich_words),
        }
        for board in program.boards
    ]
    payload = {
        "schema_version": program.schema_version,
        "reply_node": program.reply_node,
        "reply_channel": program.reply_channel,
        "boards": boards,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    counts = {board["address"]: len(board["ich_words"]) for board in boards}
    return hashlib.sha256(encoded).hexdigest(), counts


def _git_revision(path: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_dirty(path: Path) -> bool:
    return bool(
        subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )


def _command_version(command: list[str]) -> str:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _native_extension_metadata(build_profile: str) -> dict[str, Any]:
    extension = Path(_native.__file__).resolve()
    return {
        "native_build_profile": build_profile,
        "native_extension": str(extension),
        "native_extension_bytes": extension.stat().st_size,
        "native_extension_sha256": hashlib.sha256(extension.read_bytes()).hexdigest(),
    }


def run_benchmark(
    *,
    rb1_root: Path,
    samples: int,
    cold_samples: int,
    warmup: int,
    native_build_profile: str,
) -> dict[str, Any]:
    verifier = _load_verifier(rb1_root)
    timings: dict[str, dict[str, float | int]] = {}

    with tempfile.TemporaryDirectory(
        prefix="catseq-rydberg-pipeline-"
    ) as directory:
        temporary_root = Path(directory)
        request_index = 0

        def build_request() -> dict[str, Any]:
            nonlocal request_index
            request_index += 1
            return verifier._compile_request(
                TARGET_PROFILE,
                temporary_root / f"request-{request_index}",
            )

        values, request = _measure(build_request, samples=samples, warmup=warmup)
        timings["01_request_build"] = _summary(values)

        values, _payload = _measure(
            lambda: _compile_payload(request),
            samples=samples,
            warmup=warmup,
        )
        timings["02_request_json_encode"] = _summary(values)

        cold_values = []
        for index in range(cold_samples):
            cold_request = dict(request)
            cold_request["cache_dir"] = str(temporary_root / f"cold-{index}")
            cold_payload = _compile_payload(cold_request)
            gc.collect()
            started = time.perf_counter_ns()
            cold_response = _native.compile(cold_payload)
            cold_values.append((time.perf_counter_ns() - started) / 1_000_000)
            if not cold_response:
                raise RuntimeError("native compiler returned an empty cold response")
        timings["03_native_compile_cold_cache"] = _summary(cold_values)

        warm_request = dict(request)
        warm_request["cache_dir"] = str(temporary_root / "warm")
        warm_payload = _compile_payload(warm_request)
        _native.compile(warm_payload)
        values, response_bytes = _measure(
            lambda: _native.compile(warm_payload),
            samples=samples,
            warmup=warmup,
        )
        timings["04_native_compile_warm_cache"] = _summary(values)

        values, response = _measure(
            lambda: json.loads(response_bytes),
            samples=samples,
            warmup=warmup,
        )
        timings["05_response_json_decode"] = _summary(values)

        opaque_callables = _opaque_callables(request)
        values, calls_by_board = _measure(
            lambda: oasm_call_plan_to_calls(
                response["oasm_call_plan"],
                opaque_callables=opaque_callables,
            ),
            samples=samples,
            warmup=warmup,
        )
        timings["06_oasm_plan_decode"] = _summary(values)

        board_cores = _active_board_cores(request, response)
        values, sequence = _measure(
            lambda: _new_assembler(board_cores),
            samples=samples,
            warmup=warmup,
        )
        timings["07_oasm_assembler_setup"] = _summary(values)

        values, program = _measure(
            lambda: assemble_oasm_calls(calls_by_board, sequence),
            samples=samples,
            warmup=warmup,
        )
        timings["08_oasm_assembly_and_finalize"] = _summary(values)

        second_program = assemble_oasm_calls(calls_by_board, sequence)
        first_fingerprint, word_counts = _program_fingerprint(program)
        second_fingerprint, _ = _program_fingerprint(second_program)
        if first_fingerprint != second_fingerprint:
            raise RuntimeError("Rydberg runtime program is not deterministic")
        if first_fingerprint != EXPECTED_RUNTIME_PROGRAM_SHA256:
            raise RuntimeError(
                "Rydberg runtime program differs from its checked-in benchmark baseline: "
                f"{first_fingerprint}"
            )

        runtime_config = _runtime_config(program)
        values, _ = _measure(
            lambda: _prepare_until_open_failure(program, runtime_config),
            samples=samples,
            warmup=warmup,
        )
        timings["09_rust_prepare_to_safe_open_failure"] = _summary(values)

        sequence = _new_assembler(board_cores)

        def hot_offline_pipeline() -> None:
            compiled = json.loads(_native.compile(warm_payload))
            calls = oasm_call_plan_to_calls(
                compiled["oasm_call_plan"],
                opaque_callables=opaque_callables,
            )
            assembled = assemble_oasm_calls(calls, sequence)
            _prepare_until_open_failure(assembled, _runtime_config(assembled))

        values, _ = _measure(
            hot_offline_pipeline,
            samples=samples,
            warmup=warmup,
        )
        timings["10_hot_offline_pipeline_total"] = _summary(values)

    plan = response["oasm_call_plan"]
    calls = [
        call
        for epoch in plan["epochs"]
        for board in epoch["boards"]
        for call in board["calls"]
    ]
    plan_sha256 = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    baseline_path = (
        rb1_root
        / "tests"
        / "fixtures"
        / "catseq_native"
        / "rydberg_transfer.json"
    )
    baseline = json.loads(baseline_path.read_text())
    if plan_sha256 != baseline["oasm_call_plan_sha256"]:
        raise RuntimeError("Rydberg OASM call plan differs from its checked-in baseline")

    return {
        "schema_version": 1,
        "workload": {
            "entry": response["entry"],
            "pulse_time_us": 0.35,
            "srs_frequency_mhz": 484.75,
            "channels": len(request["compile_environment"]["channels"]),
            "epochs": len(plan["epochs"]),
            "oasm_calls": len(calls),
            "active_boards": len(program.boards),
            "logical_duration_cycles": response["logical_duration_cycles"],
            "logical_duration_ms": round(
                response["logical_duration_cycles"]
                / response["clock_hz"]
                * 1_000,
                3,
            ),
            "runtime_ich_words": word_counts,
            "runtime_ich_words_total": sum(word_counts.values()),
            "oasm_call_plan_sha256": plan_sha256,
            "runtime_program_sha256": first_fingerprint,
        },
        "environment": {
            "catseq_revision": _git_revision(CATSEQ_ROOT),
            "catseq_dirty": _git_dirty(CATSEQ_ROOT),
            "rb1_revision": _git_revision(rb1_root),
            "rb1_dirty": _git_dirty(rb1_root),
            "python": sys.version.split()[0],
            "rustc": _command_version(["rustc", "--version"]),
            "hardware_packets_sent": False,
            "runtime_terminal": (
                "transport_open_failed before raw socket because the configured "
                "interface name exceeds Linux IFNAMSIZ"
            ),
            **_native_extension_metadata(native_build_profile),
        },
        "timings": timings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rb1-root", type=Path, default=DEFAULT_RB1_ROOT)
    parser.add_argument("--samples", type=int, default=11)
    parser.add_argument("--cold-samples", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument(
        "--native-build-profile",
        choices=("debug", "release"),
        required=True,
        help="record the Cargo profile used to build the imported PyO3 extension",
    )
    args = parser.parse_args()
    if args.samples <= 0 or args.cold_samples <= 0 or args.warmup < 0:
        parser.error("sample counts must be positive and warmup nonnegative")

    result = run_benchmark(
        rb1_root=args.rb1_root.resolve(),
        samples=args.samples,
        cold_samples=args.cold_samples,
        warmup=args.warmup,
        native_build_profile=args.native_build_profile,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
