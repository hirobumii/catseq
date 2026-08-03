#!/usr/bin/env python3
"""Set one CatSeq release version across Python, Rust, locks, and current docs."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import re
import tomllib


VERSION_PATTERN = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def release_version(value: str) -> str:
    if VERSION_PATTERN.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("version must use MAJOR.MINOR.PATCH")
    return value


def release_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronize one CatSeq release version across the repository."
    )
    parser.add_argument("version", type=release_version)
    parser.add_argument("--date", type=release_date, default=date.today().isoformat())
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def set_section_version(text: str, section: str, version: str) -> str:
    lines = text.splitlines(keepends=True)
    in_section = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == f"[{section}]":
            in_section = True
            continue
        if in_section and stripped.startswith("["):
            break
        if in_section and stripped.startswith("version = "):
            ending = "\n" if line.endswith("\n") else ""
            lines[index] = f'version = "{version}"{ending}'
            return "".join(lines)
    raise ValueError(f"[{section}] has no version assignment")


def set_assignment(text: str, name: str, version: str) -> str:
    pattern = re.compile(rf'^{re.escape(name)}\s*=\s*"[^"]+"$', re.MULTILINE)
    updated, count = pattern.subn(f'{name} = "{version}"', text, count=1)
    if count != 1:
        raise ValueError(f"cannot find one {name} assignment")
    return updated


def set_locked_package_version(text: str, package: str, version: str) -> str:
    pattern = re.compile(
        rf'(?m)(^\[\[package\]\]\nname = "{re.escape(package)}"\nversion = ")[^"]+("$)'
    )
    updated, count = pattern.subn(
        lambda match: f"{match.group(1)}{version}{match.group(2)}",
        text,
        count=1,
    )
    if count != 1:
        raise ValueError(f"cannot find locked package {package}")
    return updated


def set_current_doc_version(
    text: str,
    current_pattern: re.Pattern[str],
    version: str,
) -> str:
    match = current_pattern.search(text)
    if match is None:
        raise ValueError("cannot find current documentation version")
    start, end = match.span("version")
    return f"{text[:start]}{version}{text[end:]}"


def add_changelog_release(text: str, version: str, released_on: str) -> str:
    heading = f"## [{version}] - {released_on}"
    existing = re.compile(
        rf"^## \[{re.escape(version)}\] - [0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$",
        re.MULTILINE,
    )
    if existing.search(text):
        return existing.sub(heading, text, count=1)
    marker = "## [Unreleased]\n"
    if text.count(marker) != 1:
        raise ValueError("CHANGELOG.md must contain one Unreleased heading")
    return text.replace(marker, f"{marker}\n{heading}\n", 1)


def set_version(root: Path, version: str, released_on: str) -> None:
    pyproject_path = root / "pyproject.toml"
    pyproject = set_section_version(
        pyproject_path.read_text(encoding="utf-8"),
        "project",
        version,
    )
    write(pyproject_path, pyproject)

    init_path = root / "catseq" / "__init__.py"
    write(
        init_path,
        set_assignment(init_path.read_text(encoding="utf-8"), "__version__", version),
    )

    rust_manifest_path = root / "rust" / "Cargo.toml"
    rust_manifest = set_section_version(
        rust_manifest_path.read_text(encoding="utf-8"),
        "workspace.package",
        version,
    )
    write(rust_manifest_path, rust_manifest)
    rust_workspace = tomllib.loads(rust_manifest)["workspace"]

    uv_lock_path = root / "uv.lock"
    write(
        uv_lock_path,
        set_locked_package_version(
            uv_lock_path.read_text(encoding="utf-8"), "catseq", version
        ),
    )

    cargo_lock_path = root / "rust" / "Cargo.lock"
    cargo_lock = cargo_lock_path.read_text(encoding="utf-8")
    for package in rust_workspace["members"]:
        cargo_lock = set_locked_package_version(cargo_lock, package, version)
    write(cargo_lock_path, cargo_lock)

    readme_path = root / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    for pattern in (
        rf"^CatSeq (?P<version>{VERSION_PATTERN.pattern}) is ",
        rf"^CatSeq (?P<version>{VERSION_PATTERN.pattern}) preserves ",
        rf"^## (?P<version>{VERSION_PATTERN.pattern}) API boundary$",
    ):
        readme = set_current_doc_version(
            readme,
            re.compile(pattern, re.MULTILINE),
            version,
        )
    write(
        readme_path,
        readme,
    )

    quickstart_path = root / "docs" / "user" / "01_quickstart.md"
    quickstart = quickstart_path.read_text(encoding="utf-8")
    for pattern in (
        rf"^# CatSeq (?P<version>{VERSION_PATTERN.pattern}) quickstart$",
        rf"^CatSeq (?P<version>{VERSION_PATTERN.pattern}) keeps ",
    ):
        quickstart = set_current_doc_version(
            quickstart,
            re.compile(pattern, re.MULTILINE),
            version,
        )
    write(
        quickstart_path,
        quickstart,
    )

    changelog_path = root / "CHANGELOG.md"
    write(
        changelog_path,
        add_changelog_release(
            changelog_path.read_text(encoding="utf-8"), version, released_on
        ),
    )


def main() -> None:
    args = parse_args()
    set_version(args.root.resolve(), args.version, args.date)
    print(f"CatSeq {args.version} metadata synchronized")


if __name__ == "__main__":
    main()
