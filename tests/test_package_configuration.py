import tomllib
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_platform_wheel_exposes_the_native_api_and_cli_without_duplicate_binary() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    maturin = project["tool"]["maturin"]

    assert maturin["manifest-path"] == "rust/catseq-python/Cargo.toml"
    assert maturin["bindings"] == "pyo3"
    assert maturin["module-name"] == "catseq._native"
    assert project["project"]["scripts"]["catseqc"] == "catseq._native:run_cli"
