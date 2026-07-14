import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _version_parts(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def test_ci_rust_toolchain_supports_the_workspace_and_installs_check_tools() -> None:
    workspace = tomllib.loads((ROOT / "rust/Cargo.toml").read_text())
    minimum = workspace["workspace"]["package"]["rust-version"]
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    match = re.search(r'^  RUST_TOOLCHAIN: "([^"]+)"$', workflow, re.MULTILINE)
    assert match is not None
    ci_toolchain = match.group(1)

    assert _version_parts(minimum) >= (1, 88), (
        "the Rust 2024 let-chains used by catseq-frontend require Rust 1.88"
    )
    assert _version_parts(ci_toolchain)[:2] == _version_parts(minimum)[:2]

    platform_job = workflow.split("\n  python-package:", 1)[0]
    install_step = platform_job.split(
        "      - name: Install the pinned Rust toolchain", 1
    )[1].split("\n      - name:", 1)[0]
    assert "--component rustfmt" in install_step
    assert "--component clippy" in install_step
