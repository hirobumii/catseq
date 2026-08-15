#!/usr/bin/env python3
"""Check every standalone source contract in ``frontend_demo/src``."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from check_demo import ContractError, check_contract, parse_contract


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat every proposed contract as an unimplemented failure",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    source_dir = Path(__file__).resolve().parent / "src"
    paths = sorted(source_dir.glob("*.py"))
    if not paths:
        print(f"FAIL {source_dir}: no frontend demos found", file=sys.stderr)
        return 1

    failures = 0
    proposed = 0
    required = 0
    for path in paths:
        try:
            contract = parse_contract(path)
            if contract.status == "proposed":
                proposed += 1
            else:
                required += 1
            passed, detail = check_contract(
                contract,
                strict=args.strict,
            )
        except (ContractError, OSError) as error:
            passed = False
            detail = str(error)

        if not passed:
            failures += 1
        label = "PASS" if passed else "FAIL"
        print(f"{label} {path.relative_to(source_dir.parent)}: {detail}")

    print(
        f"checked {len(paths)} demos: {required} required, "
        f"{proposed} proposed, {failures} failed"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
