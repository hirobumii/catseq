"""PROTOTYPE ONLY: build the real Rydberg Morphism with an arena DAG runtime."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import fields, is_dataclass
from enum import Enum
from hashlib import sha256
import io
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter_ns
import tracemalloc


WORKSPACE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKSPACE / "rb1-next"))
sys.path.insert(0, str(WORKSPACE / "catseq"))

from catseq.morphism.core import Morphism as LegacyMorphism  # noqa: E402
from experiments.computing.rydberg_transfer import RydbergTransferExp  # noqa: E402
from oasm.dev.main import C_MAIN  # noqa: E402
from oasm.dev.rsp import C_RSP  # noqa: E402
from oasm.dev.rwg import C_RWG  # noqa: E402
from oasm.rtmq2 import assembler  # noqa: E402
from rb1system.abstract.params import ExpParams  # noqa: E402

from arena_runtime import ArenaMorphism, build_arena, install  # noqa: E402


OFFLINE_NODES = (
    *((f"rwg{index}", C_RWG) for index in (0, 1, 2, 3, 4, 5, 8, 9)),
    *((f"rsp{index}", C_RSP) for index in (6, 7, 10, 11)),
    ("main", C_MAIN),
)


def _runtime(pulse_time_us: float, frequency_mhz: float):
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
    return experiment, params


def _timed_build(experiment, params):
    sink = io.StringIO()
    started = perf_counter_ns()
    with redirect_stdout(sink):
        morphism = experiment.build_sequence(params)
    return morphism, perf_counter_ns() - started


def _timed_materialize(morphism):
    sink = io.StringIO()
    started = perf_counter_ns()
    with redirect_stdout(sink):
        _ = morphism.lanes
    return perf_counter_ns() - started


def _stable(value: object) -> object:
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
        return tuple(_stable(item) for item in value)
    if isinstance(value, list):
        return tuple(_stable(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((repr(key), _stable(item)) for key, item in value.items()))
    if is_dataclass(value) and not isinstance(value, type):
        return (
            type(value).__module__,
            type(value).__qualname__,
            tuple(
                (field.name, _stable(getattr(value, field.name)))
                for field in fields(value)
                if field.name not in {"debug_id", "debug_trace"}
            ),
        )
    return (type(value).__module__, type(value).__qualname__, repr(value))


def _morphism_fingerprint(morphism) -> str:
    semantic = []
    for channel in sorted(morphism.lanes, key=lambda item: item.global_id):
        semantic.append(
            (
                channel.global_id,
                tuple(
                    (
                        operation.operation_type.name,
                        _stable(operation.start_state),
                        _stable(operation.end_state),
                        _stable(operation.duration_cycles),
                    )
                    for operation in morphism.lanes[channel].operations
                ),
            )
        )
    return sha256(repr(tuple(semantic)).encode("utf-8")).hexdigest()


def _shape(morphism) -> dict[str, object]:
    return {
        "duration_cycles": morphism.total_duration_cycles,
        "lane_count": len(morphism.lanes),
        "operation_count": sum(
            len(lane.operations) for lane in morphism.lanes.values()
        ),
        "semantic_hash": _morphism_fingerprint(morphism),
    }


def _median_ms(samples: list[int]) -> float:
    return median(samples) / 1_000_000


def benchmark(*, pulse_time_us: float, frequency_mhz: float, repeats: int):
    baseline_experiment, baseline_params = _runtime(pulse_time_us, frequency_mhz)
    _timed_build(baseline_experiment, baseline_params)
    baseline_times: list[int] = []
    baseline_peaks: list[int] = []
    baseline_morphism = None
    for _ in range(repeats):
        baseline_morphism, elapsed = _timed_build(
            baseline_experiment, baseline_params
        )
        baseline_times.append(elapsed)
    for _ in range(repeats):
        tracemalloc.start()
        baseline_morphism, _ = _timed_build(
            baseline_experiment, baseline_params
        )
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        baseline_peaks.append(peak)
    if not isinstance(baseline_morphism, LegacyMorphism):
        raise AssertionError("baseline was unexpectedly patched")
    baseline_shape = _shape(baseline_morphism)

    install()
    arena_experiment, arena_params = _runtime(pulse_time_us, frequency_mhz)
    lazy_times: list[int] = []
    materialize_times: list[int] = []
    arena_lazy_peaks: list[int] = []
    arena_materialized_peaks: list[int] = []
    stats_before_final_materialize = None
    stats_after_final_materialize = None
    arena_morphism = None

    with build_arena():
        _timed_build(arena_experiment, arena_params)

    for _ in range(repeats):
        with build_arena() as arena:
            arena_morphism, elapsed = _timed_build(arena_experiment, arena_params)
            lazy_times.append(elapsed)
            stats_before_final_materialize = arena.stats()
            materialize_times.append(_timed_materialize(arena_morphism))
            stats_after_final_materialize = arena.stats()

    for _ in range(repeats):
        with build_arena() as arena:
            tracemalloc.start()
            arena_morphism, _ = _timed_build(arena_experiment, arena_params)
            _, lazy_peak = tracemalloc.get_traced_memory()
            _timed_materialize(arena_morphism)
            _, materialized_peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            arena_lazy_peaks.append(lazy_peak)
            arena_materialized_peaks.append(materialized_peak)

    if not isinstance(arena_morphism, ArenaMorphism):
        raise AssertionError("arena runtime did not produce ArenaMorphism")
    arena_shape = _shape(arena_morphism)
    if arena_shape != baseline_shape:
        raise AssertionError(
            "arena Morphism differs from baseline: "
            + json.dumps(
                {"baseline": baseline_shape, "arena": arena_shape},
                indent=2,
                sort_keys=True,
            )
        )

    return {
        "parameters": {
            "pulse_time_us": pulse_time_us,
            "frequency_mhz": frequency_mhz,
            "repeats": repeats,
        },
        "artifact": baseline_shape,
        "baseline": {
            "full_build_sequence_ms": _median_ms(baseline_times),
            "peak_kib": median(baseline_peaks) / 1024,
        },
        "arena": {
            "full_build_sequence_to_lazy_dag_ms": _median_ms(lazy_times),
            "final_lane_materialize_ms": _median_ms(materialize_times),
            "full_build_sequence_plus_lane_materialize_ms": _median_ms(
                [
                    lazy + materialize
                    for lazy, materialize in zip(
                        lazy_times, materialize_times, strict=True
                    )
                ]
            ),
            "lazy_peak_kib": median(arena_lazy_peaks) / 1024,
            "materialized_peak_kib": median(arena_materialized_peaks) / 1024,
            "stats_before_final_materialize": stats_before_final_materialize,
            "stats_after_final_materialize": stats_after_final_materialize,
        },
        "safety": {
            "assembler_interface": None,
            "final_compile_called": False,
            "seq_run_called": False,
        },
        "prototype_limitations": [
            "provenance breadcrumbs are stored on composition nodes and applied during Lane materialization",
            "deferred channel applications, end-state views, state-dependent batches, and hardware repeats remain unexpanded during build_sequence",
            "the compatibility materializer performs the deferred work; a production compiler must consume these DAG nodes directly",
            "requesting an unknown duration or concrete state before compilation intentionally forces the relevant deferred node",
        ],
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
    print("\033[1mPROTOTYPE — real Rydberg arena Morphism build\033[0m")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
