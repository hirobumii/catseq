from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[2]
SYNC_SCRIPT = ROOT / "tools" / "set_version.py"
VERSION_FILES = (
    "CHANGELOG.md",
    "README.md",
    "catseq/__init__.py",
    "docs/user/01_quickstart.md",
    "pyproject.toml",
    "rust/Cargo.lock",
    "rust/Cargo.toml",
    "uv.lock",
)


def test_set_version_updates_current_metadata_without_rewriting_history(
    tmp_path: Path,
) -> None:
    for relative_path in VERSION_FILES:
        source = ROOT / relative_path
        destination = tmp_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    pyproject_before = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    previous_version = pyproject_before["project"]["version"]
    readme_path = tmp_path / "README.md"
    readme_path.write_text(
        readme_path.read_text()
        + f"\nHistorical note about CatSeq {previous_version}.\n"
    )
    changelog_path = tmp_path / "CHANGELOG.md"
    changelog_path.write_text(
        changelog_path.read_text().replace(
            "## [Unreleased]\n",
            "## [Unreleased]\n\n### Added\n\n- Next release feature.\n",
            1,
        )
    )

    command = [
        sys.executable,
        str(SYNC_SCRIPT),
        "9.8.7",
        "--date",
        "2030-01-02",
        "--root",
        str(tmp_path),
    ]
    subprocess.run(command, check=True)
    command[4] = "2030-01-03"
    subprocess.run(command, check=True)

    pyproject = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    rust_workspace = tomllib.loads((tmp_path / "rust/Cargo.toml").read_text())
    uv_lock = tomllib.loads((tmp_path / "uv.lock").read_text())
    cargo_lock = tomllib.loads((tmp_path / "rust/Cargo.lock").read_text())

    assert pyproject["project"]["version"] == "9.8.7"
    assert rust_workspace["workspace"]["package"]["version"] == "9.8.7"
    assert (
        next(package for package in uv_lock["package"] if package["name"] == "catseq")[
            "version"
        ]
        == "9.8.7"
    )

    workspace_members = set(rust_workspace["workspace"]["members"])
    assert {
        package["version"]
        for package in cargo_lock["package"]
        if package["name"] in workspace_members
    } == {"9.8.7"}

    assert '__version__ = "9.8.7"' in (tmp_path / "catseq/__init__.py").read_text()

    readme = (tmp_path / "README.md").read_text()
    assert "CatSeq 9.8.7 is" in readme
    assert "## 9.8.7 API boundary" in readme
    assert "There is currently no public" in readme
    assert "The removed 0.4 `Compiler`" in readme
    assert f"Historical note about CatSeq {previous_version}." in readme

    quickstart = (tmp_path / "docs/user/01_quickstart.md").read_text()
    assert quickstart.startswith("# CatSeq 9.8.7 quickstart\n")

    changelog = (tmp_path / "CHANGELOG.md").read_text()
    assert "## [9.8.7] - 2030-01-02" not in changelog
    assert changelog.count("## [9.8.7] - 2030-01-03") == 1
    assert (
        changelog.index("## [Unreleased]")
        < changelog.index("## [9.8.7] - 2030-01-03")
        < changelog.index("- Next release feature.")
    )
    assert "## [0.3.2] - 2026-08-03" in changelog
