"""PROTOTYPE ONLY: cProfile the real baseline or arena Rydberg build."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import cProfile
import io
from pathlib import Path
import pstats
import sys


WORKSPACE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKSPACE / "rb1-next"))
sys.path.insert(0, str(WORKSPACE / "catseq"))

from real_rydberg_arena import _runtime, _timed_build  # noqa: E402
from arena_runtime import build_arena, install  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("baseline", "arena"))
    parser.add_argument("--iterations", type=int, default=15)
    parser.add_argument("--limit", type=int, default=45)
    args = parser.parse_args()

    experiment, params = _runtime(0.35, 484.75)
    if args.mode == "arena":
        install()
        experiment, params = _runtime(0.35, 484.75)
        with build_arena():
            _timed_build(experiment, params)
    else:
        _timed_build(experiment, params)

    profiler = cProfile.Profile()
    profiler.enable()
    if args.mode == "arena":
        for _ in range(args.iterations):
            with build_arena():
                _timed_build(experiment, params)
    else:
        for _ in range(args.iterations):
            _timed_build(experiment, params)
    profiler.disable()

    output = io.StringIO()
    stats = pstats.Stats(profiler, stream=output).strip_dirs().sort_stats("cumulative")
    stats.print_stats(args.limit)
    with redirect_stdout(sys.stdout):
        print(f"PROTOTYPE profile mode={args.mode} iterations={args.iterations}")
        print(output.getvalue())


if __name__ == "__main__":
    main()
