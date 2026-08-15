#!/usr/bin/env python3
"""Check one executable CatSeq frontend contract without importing its source."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import re
import sys


_HEADER = re.compile(r"^# ([A-Z][A-Z-]*):(?: (.*))?$")
_SINGLE_VALUE_KEYS = (
    "CATSEQ-DEMO",
    "STATUS",
    "ISSUE",
    "ENTRY",
    "EXPECT",
)
_ALLOWED_KEYS = frozenset(_SINGLE_VALUE_KEYS) | {
    "CONTRACT",
    "DIAGNOSTIC",
    "LINK-BINDING",
}


@dataclass(frozen=True)
class DemoContract:
    path: Path
    status: str
    issue: str
    entry: str
    expectation: str
    contracts: tuple[str, ...]
    diagnostics: tuple[str, ...]
    link_bindings: tuple[str, ...]


class ContractError(ValueError):
    """The source file does not contain a valid frontend demo contract."""


def parse_contract(path: Path) -> DemoContract:
    """Parse the leading NAC3-style expectation comments from one demo."""

    source = path.read_text(encoding="utf-8")
    try:
        ast.parse(source, filename=str(path))
    except SyntaxError as error:
        location = f"{error.lineno}:{error.offset}" if error.lineno else "unknown"
        raise ContractError(
            f"{path}:{location}: invalid Python syntax: {error.msg}"
        ) from error

    values: dict[str, list[str]] = {}
    for line in source.splitlines():
        if not line:
            if values:
                break
            continue
        match = _HEADER.fullmatch(line)
        if match is None:
            if values:
                break
            if line.startswith("#"):
                continue
            break
        key, value = match.groups()
        values.setdefault(key, []).append(value or "")

    def one(key: str) -> str:
        entries = values.get(key, [])
        if len(entries) != 1 or not entries[0]:
            raise ContractError(f"{path}: expected exactly one non-empty {key} header")
        return entries[0]

    for key in _SINGLE_VALUE_KEYS:
        entries = values.get(key, [])
        if len(entries) > 1:
            raise ContractError(f"{path}: {key} may appear only once")
    unknown = sorted(values.keys() - _ALLOWED_KEYS)
    if unknown:
        raise ContractError(f"{path}: unknown contract headers: {unknown!r}")

    if one("CATSEQ-DEMO") != "1":
        raise ContractError(f"{path}: unsupported CATSEQ-DEMO version")

    status = one("STATUS")
    if status not in {"proposed", "required"}:
        raise ContractError(f"{path}: STATUS must be proposed or required")

    issue = one("ISSUE")
    if re.fullmatch(r"#[1-9][0-9]*", issue) is None:
        raise ContractError(f"{path}: ISSUE must be a GitHub issue such as #56")

    entry = one("ENTRY")
    if any(not part.isidentifier() for part in entry.split(".")):
        raise ContractError(f"{path}: ENTRY must be a qualified Python name")

    expectation = one("EXPECT")
    if expectation not in {"accept", "reject"}:
        raise ContractError(f"{path}: EXPECT must be accept or reject")

    contracts = tuple(item for item in values.get("CONTRACT", []) if item)
    if not contracts:
        raise ContractError(f"{path}: at least one CONTRACT is required")

    diagnostics = tuple(item for item in values.get("DIAGNOSTIC", []) if item)
    if expectation == "reject" and not diagnostics:
        raise ContractError(f"{path}: rejected demos require a DIAGNOSTIC substring")
    if expectation == "accept" and diagnostics:
        raise ContractError(f"{path}: accepted demos cannot declare DIAGNOSTIC")

    link_bindings = tuple(item for item in values.get("LINK-BINDING", []) if item)
    if len(set(link_bindings)) != len(link_bindings):
        raise ContractError(f"{path}: duplicate LINK-BINDING declarations")
    if any(not item.isidentifier() for item in link_bindings):
        raise ContractError(f"{path}: LINK-BINDING values must be parameter names")

    return DemoContract(
        path=path,
        status=status,
        issue=issue,
        entry=entry,
        expectation=expectation,
        contracts=contracts,
        diagnostics=diagnostics,
        link_bindings=link_bindings,
    )


def check_contract(
    contract: DemoContract,
    *,
    strict: bool,
) -> tuple[bool, str]:
    """Validate a proposed contract without importing compiler-only source."""

    if contract.status == "proposed":
        if strict:
            return False, "proposed contract has not been implemented"
        return True, "proposed contract is well formed"

    return (
        False,
        "required contracts need the future public registered-source analysis "
        "adapter; keep this contract proposed until that adapter exists",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat every proposed contract as an unimplemented failure",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        contract = parse_contract(args.source)
        passed, detail = check_contract(
            contract,
            strict=args.strict,
        )
    except (ContractError, OSError) as error:
        print(f"FAIL {args.source}: {error}", file=sys.stderr)
        return 1

    label = "PASS" if passed else "FAIL"
    stream = sys.stdout if passed else sys.stderr
    print(f"{label} {args.source}: {detail}", file=stream)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
