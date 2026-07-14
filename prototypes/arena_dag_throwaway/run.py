"""Terminal runner for the throwaway arena-DAG prototype."""

from __future__ import annotations

import argparse
import json

from logic import benchmark_depth, benchmark_incremental, benchmark_representations, run_all


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="run once and exit")
    parser.add_argument("--sizes", nargs="+", type=int, default=(1_000, 3_000, 10_000))
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--deep-size", type=int, default=100_000)
    parser.add_argument("--incremental-size", type=int, default=30_000)
    parser.add_argument("--binds", type=int, default=100)
    return parser.parse_args()


def show(value: object, *, clear: bool) -> None:
    if clear:
        print("\033[2J\033[H", end="")
    print("\033[1mPROTOTYPE — arena DAG state\033[0m")
    print(json.dumps(value, indent=2, sort_keys=True))


def interactive(args: argparse.Namespace) -> None:
    state: dict[str, object] = {
        "question": "Can an arena DAG preserve >> structure safely and cheaply?",
        "last_action": "none",
        "result": None,
    }
    while True:
        show(state, clear=True)
        print("\n\033[1m[a]\033[0m all  \033[1m[b]\033[0m build/memory  "
              "\033[1m[d]\033[0m depth  \033[1m[i]\033[0m incremental  "
              "\033[1m[q]\033[0m quit")
        action = input("> ").strip().lower()
        if action == "q":
            return
        if action == "a":
            result = run_all(
                sizes=tuple(args.sizes),
                repeats=args.repeats,
                deep_size=args.deep_size,
                incremental_size=args.incremental_size,
                binds=args.binds,
            )
        elif action == "b":
            result = benchmark_representations(tuple(args.sizes), args.repeats)
        elif action == "d":
            result = benchmark_depth(args.deep_size, args.repeats)
        elif action == "i":
            result = benchmark_incremental(
                args.incremental_size, args.binds, args.repeats
            )
        else:
            continue
        state = {**state, "last_action": action, "result": result}


def main() -> None:
    args = parse_args()
    if args.all:
        show(
            run_all(
                sizes=tuple(args.sizes),
                repeats=args.repeats,
                deep_size=args.deep_size,
                incremental_size=args.incremental_size,
                binds=args.binds,
            ),
            clear=False,
        )
        return
    interactive(args)


if __name__ == "__main__":
    main()
