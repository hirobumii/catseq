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


def test_ci_and_release_target_only_linux_x86_64() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    platform_job, python_and_release_jobs = workflow.split("\n  python-package:", 1)
    python_job, release_job = python_and_release_jobs.split("\n  release:", 1)

    assert re.findall(r"^\s+os: (\S+)$", platform_job, re.MULTILINE) == [
        "ubuntu-24.04"
    ]
    assert re.findall(r"^\s+target: (\S+)$", platform_job, re.MULTILINE) == [
        "x86_64-unknown-linux-gnu"
    ]
    assert "artifact:" not in platform_job
    assert "    runs-on: ${{ matrix.os }}" in platform_job
    assert "    runs-on: ubuntu-24.04" in python_job
    assert "    runs-on: ubuntu-24.04" in release_job

    windows_paths = (
        "windows-2025",
        "x86_64-pc-windows-msvc",
        "catseqc-windows-x86_64",
        "runner.os == 'Windows'",
        "LLVM-22.1.6-win64",
        "Build the Windows wheel",
        "Install the Windows wheel into a clean environment",
        "Package the Windows compiler",
    )
    for windows_path in windows_paths:
        assert windows_path not in workflow


def test_installation_docs_state_the_linux_x86_64_support_boundary() -> None:
    support_boundary = (
        "Current CI, release artifacts, and physical deployment support "
        "Linux x86_64 only."
    )

    assert support_boundary in (ROOT / "README.md").read_text()
    assert support_boundary in (ROOT / "docs/user/01_quickstart.md").read_text()


def test_ci_enforces_typing_and_builds_the_native_wheel() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()

    assert "uv run mypy catseq" in workflow
    assert "run_readme_quickstart.py" not in workflow
    python_job = workflow.split("\n  python-package:", 1)[1].split(
        "\n  release:", 1
    )[0]
    assert "      - name: Install LLVM 22 development libraries" in python_job


def test_ci_exposes_the_llvm_tools_required_to_build_nac3_irrt() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    platform_job, python_and_release_jobs = workflow.split("\n  python-package:", 1)

    linux_step = platform_job.split(
        "      - name: Install LLVM 22 development libraries", 1
    )[1].split("\n      - name:", 1)[0]
    assert "clang-22 llvm-22-dev" in linux_step
    assert '"$RUNNER_TEMP/clang-irrt"' in linux_step
    assert '"$RUNNER_TEMP/llvm-as-irrt"' in linux_step
    assert 'echo "$RUNNER_TEMP" >> "$GITHUB_PATH"' in linux_step

    python_job = python_and_release_jobs.split("\n  release:", 1)[0]
    python_llvm_step = python_job.split(
        "      - name: Install LLVM 22 development libraries", 1
    )[1].split("\n      - name:", 1)[0]
    assert "clang-22 llvm-22-dev" in python_llvm_step
    assert '"$RUNNER_TEMP/clang-irrt"' in python_llvm_step
    assert '"$RUNNER_TEMP/llvm-as-irrt"' in python_llvm_step
    assert 'echo "$RUNNER_TEMP" >> "$GITHUB_PATH"' in python_llvm_step


def test_fork_pull_requests_keep_public_rust_checks_without_private_secrets() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    fork_guard = (
        "github.event_name != 'pull_request' || "
        "github.event.pull_request.head.repo.full_name == github.repository"
    )
    platform_job = workflow.split("\n  python-package:", 1)[0]
    private_steps = (
        "Configure private Git credentials",
        "Sync the fixed Python environment",
        "Check Python code",
        "Run Python tests",
        "Run Python type checks",
    )
    for step_name in private_steps:
        step = platform_job.split(f"      - name: {step_name}", 1)[1].split(
            "\n      - name:", 1
        )[0]
        assert fork_guard in step, step_name

    public_steps = (
        "Install LLVM 22 development libraries",
        "Check Rust formatting",
        "Lint the Rust workspace",
        "Test the Rust workspace",
    )
    for step_name in public_steps:
        step = platform_job.split(f"      - name: {step_name}", 1)[1].split(
            "\n      - name:", 1
        )[0]
        assert fork_guard not in step, step_name

    python_job = workflow.split("\n  python-package:", 1)[1].split(
        "\n  release:", 1
    )[0]
    assert fork_guard in python_job.split("\n    steps:", 1)[0]


def test_ci_does_not_publish_the_removed_standalone_compiler() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()

    assert "catseqc" not in workflow
    release_job = workflow.split("\n  release:", 1)[1]
    needs = release_job.split("\n    runs-on:", 1)[0]
    assert "- python-package" in needs
    assert "- platform" in needs
