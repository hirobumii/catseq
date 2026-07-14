"""PROTOTYPE ONLY: bind two scan values to one real Rydberg arena template.

Question: can a scan point update a small binding overlay while retaining the
same DAG topology, and then reproduce concrete builds at two pulse durations?
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import gc
import io
import json
from statistics import median
from time import perf_counter_ns

from catseq.expr import var
from rb1system.abstract.params import ExpParams

from arena_runtime import ArenaMorphism, build_arena, install
from real_rydberg_arena import _runtime, _shape, _timed_build
from scan_binding_logic import node_parameter_dependencies, reverse_parameter_index


PARAMETER = "pulse_time_us"


def _median_fork_ms(arena, value: float, repeats: int) -> float:
    samples = []
    gc.disable()
    try:
        for _ in range(repeats):
            started = perf_counter_ns()
            bound_arena = arena.fork({PARAMETER: value})
            samples.append(perf_counter_ns() - started)
            del bound_arena
    finally:
        gc.enable()
    return median(samples) / 1_000_000


def _materialize_binding(template, root: int, value: float):
    bound_arena = template.fork({PARAMETER: value})
    bound = ArenaMorphism._from_root(bound_arena, root)
    sink = io.StringIO()
    started = perf_counter_ns()
    with redirect_stdout(sink):
        _ = bound.lanes
    materialize_ms = (perf_counter_ns() - started) / 1_000_000
    return _shape(bound), materialize_ms, bound_arena.stats()


def benchmark(values: tuple[float, ...], fork_repeats: int) -> dict[str, object]:
    concrete_shapes = {}
    for value in values:
        experiment, params = _runtime(value, 484.75)
        concrete, _ = _timed_build(experiment, params)
        concrete_shapes[str(value)] = _shape(concrete)

    install()
    experiment, _ = _runtime(values[0], 484.75)
    symbolic_params = ExpParams(
        {
            experiment.srs_frequency: 484.75,
            experiment.pulse_time: var(PARAMETER),
        }
    )
    with build_arena() as template:
        symbolic, template_build_ns = _timed_build(experiment, symbolic_params)
    root = symbolic._root
    template_node_count = len(template.kinds)
    dependencies = node_parameter_dependencies(template)
    reverse_index = reverse_parameter_index(dependencies)

    updates = {}
    for value in values:
        shape, materialize_ms, bound_stats = _materialize_binding(
            template,
            root,
            value,
        )
        expected = concrete_shapes[str(value)]
        if shape != expected:
            raise AssertionError(
                json.dumps(
                    {"value": value, "expected": expected, "actual": shape},
                    indent=2,
                    sort_keys=True,
                )
            )
        updates[str(value)] = {
            "binding_fork_ms": _median_fork_ms(template, value, fork_repeats),
            "compatibility_materialize_ms": materialize_ms,
            "artifact": shape,
            "bound_node_count_after_materialize": bound_stats["node_count"],
            "semantic_match": True,
        }

    if len(template.kinds) != template_node_count:
        raise AssertionError("binding evaluation mutated the shared template")

    dirty_nodes = reverse_index.get(PARAMETER, ())
    return {
        "question": "Can scan binding retain one DAG and match concrete builds?",
        "template": {
            "build_ms": template_build_ns / 1_000_000,
            "node_count": template_node_count,
            "root": root,
            "parameter_dependencies": sorted(dependencies[root]),
            "unchanged_after_bindings": True,
        },
        "dependency_index": {
            "parameter": PARAMETER,
            "dirty_node_count": len(dirty_nodes),
            "dirty_nodes": dirty_nodes,
        },
        "updates": updates,
        "safety": {
            "final_compile_called": False,
            "seq_run_called": False,
        },
    }


def _show(state: object, *, clear: bool) -> None:
    if clear:
        print("\033[2J\033[H", end="")
    print("\033[1mPROTOTYPE — Rydberg scan binding\033[0m")
    print(json.dumps(state, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--values", nargs="+", type=float, default=(0.35, 0.55))
    parser.add_argument("--fork-repeats", type=int, default=501)
    args = parser.parse_args()
    result = benchmark(tuple(args.values), args.fork_repeats)
    if args.all:
        _show(result, clear=False)
        return
    selected = str(args.values[0])
    while True:
        state = {
            "template": result["template"],
            "dependency_index": result["dependency_index"],
            "selected_binding": selected,
            "update": result["updates"][selected],
        }
        _show(state, clear=True)
        print("\n\033[1m[1]\033[0m first value  \033[1m[2]\033[0m second value  \033[1m[q]\033[0m quit")
        action = input("> ").strip().lower()
        if action == "q":
            return
        if action == "1":
            selected = str(args.values[0])
        elif action == "2" and len(args.values) > 1:
            selected = str(args.values[1])


if __name__ == "__main__":
    main()
