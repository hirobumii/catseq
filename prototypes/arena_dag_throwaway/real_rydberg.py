"""PROTOTYPE ONLY: offline compile the real rb1-next Rydberg morphism.

This script deliberately stops before execution.  It creates an OASM assembler
with ``interface=None``, builds the real ``RydbergTransferExp`` Morphism, runs
the CatSeq compiler passes, and generates assembly in memory.  It never opens a
BaseExp lifecycle and never calls ``seq.run()``.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass, fields, is_dataclass
from enum import Enum
from hashlib import sha256
import io
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter_ns


WORKSPACE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKSPACE / "rb1-next"))
sys.path.insert(0, str(WORKSPACE / "catseq"))

from catseq.compilation.compiler import execute_oasm_calls  # noqa: E402
from catseq.compilation.pipeline import (  # noqa: E402
    analyze_costs_and_epochs,
    extract_and_translate,
    generate_final_calls,
    schedule_and_optimize,
    validate_constraints,
)
from catseq.expr import contains_expr  # noqa: E402
from experiments.computing.rydberg_transfer import RydbergTransferExp  # noqa: E402
from oasm.dev.main import C_MAIN  # noqa: E402
from oasm.dev.rsp import C_RSP  # noqa: E402
from oasm.dev.rwg import C_RWG  # noqa: E402
from oasm.rtmq2 import assembler  # noqa: E402
from rb1system.abstract.params import ExpParams  # noqa: E402


OFFLINE_NODES = (
    *((f"rwg{index}", C_RWG) for index in (0, 1, 2, 3, 4, 5, 8, 9)),
    *((f"rsp{index}", C_RSP) for index in (6, 7, 10, 11)),
    ("main", C_MAIN),
)


@dataclass(frozen=True, slots=True)
class StageMedians:
    build_morphism_ms: float
    contains_expr_ms: float
    extract_translate_ms: float
    analyze_costs_epochs_ms: float
    schedule_optimize_ms: float
    validate_ms: float
    generate_calls_ms: float
    assemble_in_memory_ms: float
    compiler_total_ms: float
    build_compile_assembly_ms: float


def _timed(operation):
    sink = io.StringIO()
    started = perf_counter_ns()
    with redirect_stdout(sink):
        value = operation()
    return value, perf_counter_ns() - started


def _assembly_tables(sequence) -> dict[str, tuple[int, ...]]:
    tables: dict[str, tuple[int, ...]] = {}
    for name in sequence.asm.multi:
        table = sequence.asm[name]
        if len(table):
            tables[name] = tuple(int(value) for value in table)
    return tables


def _hash_value(value: object) -> str:
    return sha256(repr(value).encode("utf-8")).hexdigest()


def _stable_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if isinstance(value, Enum):
        return (type(value).__module__, type(value).__qualname__, value.name)
    if callable(value):
        code = getattr(value, "__code__", None)
        return (
            "callable",
            getattr(value, "__module__", None),
            getattr(value, "__qualname__", type(value).__qualname__),
            getattr(code, "co_filename", None),
            getattr(code, "co_firstlineno", None),
        )
    if isinstance(value, tuple):
        return tuple(_stable_value(item) for item in value)
    if isinstance(value, list):
        return tuple(_stable_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(
            sorted((repr(key), _stable_value(item)) for key, item in value.items())
        )
    if is_dataclass(value) and not isinstance(value, type):
        return (
            type(value).__module__,
            type(value).__qualname__,
            tuple(
                (field.name, _stable_value(getattr(value, field.name)))
                for field in fields(value)
                if field.name not in {"debug_id", "debug_trace"}
            ),
        )
    return (type(value).__module__, type(value).__qualname__, repr(value))


def _calls_fingerprint(calls_by_board) -> str:
    normalized = []
    for address in sorted(calls_by_board, key=lambda item: item.value):
        for call in calls_by_board[address]:
            normalized.append(
                (
                    address.value,
                    call.dsl_func.name,
                    _stable_value(call.args),
                    _stable_value(call.kwargs),
                )
            )
    return _hash_value(tuple(normalized))


def _median_ms(samples: list[int]) -> float:
    return median(samples) / 1_000_000


def benchmark(*, pulse_time_us: float, frequency_mhz: float, repeats: int) -> dict[str, object]:
    sequence = assembler(None, list(OFFLINE_NODES))
    experiment = RydbergTransferExp(
        device_list=object(),
        execution_mode="simulation",
        repeat_count=1,
        scan_frequencies_mhz=(frequency_mhz,),
        scan_times_us=(pulse_time_us,),
    )
    experiment.seq = sequence
    params = ExpParams(
        {
            experiment.srs_frequency: frequency_mhz,
            experiment.pulse_time: pulse_time_us,
        }
    )

    stages: dict[str, list[int]] = {
        name: []
        for name in (
            "build",
            "contains",
            "extract",
            "analyze",
            "schedule",
            "validate",
            "generate",
            "assemble",
        )
    }
    observations: list[dict[str, object]] = []

    # Warm all import-, factory-, and disassembler-level caches. This is still
    # pure compilation and assembly; no execution method is called.
    warm_morphism, _ = _timed(lambda: experiment.build_sequence(params))
    warm_events = extract_and_translate(warm_morphism)
    analyze_costs_and_epochs(warm_events, sequence)
    schedule_and_optimize(warm_events)
    validate_constraints(warm_events)
    warm_calls = generate_final_calls(warm_events)
    with redirect_stdout(io.StringIO()):
        execute_oasm_calls(warm_calls, sequence)

    for _ in range(repeats):
        morphism, elapsed = _timed(lambda: experiment.build_sequence(params))
        stages["build"].append(elapsed)

        symbolic, elapsed = _timed(lambda: contains_expr(morphism))
        stages["contains"].append(elapsed)
        if symbolic:
            raise AssertionError("real Rydberg Morphism unexpectedly remained symbolic")

        events, elapsed = _timed(lambda: extract_and_translate(morphism))
        stages["extract"].append(elapsed)

        _, elapsed = _timed(lambda: analyze_costs_and_epochs(events, sequence))
        stages["analyze"].append(elapsed)

        _, elapsed = _timed(lambda: schedule_and_optimize(events))
        stages["schedule"].append(elapsed)

        _, elapsed = _timed(lambda: validate_constraints(events))
        stages["validate"].append(elapsed)

        calls, elapsed = _timed(lambda: generate_final_calls(events))
        stages["generate"].append(elapsed)

        _, elapsed = _timed(lambda: execute_oasm_calls(calls, sequence))
        stages["assemble"].append(elapsed)

        tables = _assembly_tables(sequence)
        observations.append(
            {
                "duration_cycles": morphism.total_duration_cycles,
                "lane_count": len(morphism.lanes),
                "operation_count": sum(
                    len(lane.operations) for lane in morphism.lanes.values()
                ),
                "event_count": sum(len(board_events) for board_events in events.values()),
                "call_count": sum(len(board_calls) for board_calls in calls.values()),
                "active_boards": tuple(sorted(tables)),
                "instructions_by_board": tuple(
                    sorted((name, len(table)) for name, table in tables.items())
                ),
                "calls_hash": _calls_fingerprint(calls),
                "assembly_hash": _hash_value(tuple(sorted(tables.items()))),
            }
        )

    differing = {
        key: [observation[key] for observation in observations]
        for key in observations[0]
        if any(observation[key] != observations[0][key] for observation in observations[1:])
    }
    if differing:
        raise AssertionError(
            "repeated offline compilation produced different artifacts: "
            + json.dumps(differing, default=str, sort_keys=True)
        )

    compiler_sample_totals = [
        sum(
            stages[name][index]
            for name in ("contains", "extract", "analyze", "schedule", "validate", "generate")
        )
        for index in range(repeats)
    ]
    end_to_end_sample_totals = [
        stages["build"][index]
        + compiler_sample_totals[index]
        + stages["assemble"][index]
        for index in range(repeats)
    ]
    medians = StageMedians(
        build_morphism_ms=_median_ms(stages["build"]),
        contains_expr_ms=_median_ms(stages["contains"]),
        extract_translate_ms=_median_ms(stages["extract"]),
        analyze_costs_epochs_ms=_median_ms(stages["analyze"]),
        schedule_optimize_ms=_median_ms(stages["schedule"]),
        validate_ms=_median_ms(stages["validate"]),
        generate_calls_ms=_median_ms(stages["generate"]),
        assemble_in_memory_ms=_median_ms(stages["assemble"]),
        compiler_total_ms=_median_ms(compiler_sample_totals),
        build_compile_assembly_ms=_median_ms(end_to_end_sample_totals),
    )
    return {
        "safety": {
            "assembler_interface": None,
            "base_exp_context_opened": False,
            "seq_run_called": False,
        },
        "parameters": {
            "frequency_mhz": frequency_mhz,
            "pulse_time_us": pulse_time_us,
            "repeats": repeats,
        },
        "artifact": observations[0],
        "medians": asdict(medians),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pulse-time-us", type=float, default=0.35)
    parser.add_argument("--frequency-mhz", type=float, default=484.75)
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    result = benchmark(
        pulse_time_us=args.pulse_time_us,
        frequency_mhz=args.frequency_mhz,
        repeats=args.repeats,
    )
    print("\033[1mPROTOTYPE — real Rydberg offline compilation\033[0m")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
