import ast
import tomllib
from pathlib import Path

from catseq import _native


ROOT = Path(__file__).parents[1]


def test_platform_wheel_exposes_the_native_api_and_cli_without_duplicate_binary() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    maturin = project["tool"]["maturin"]

    assert maturin["manifest-path"] == "rust/catseq-python/Cargo.toml"
    assert maturin["bindings"] == "pyo3"
    assert maturin["module-name"] == "catseq._native"
    assert project["project"]["scripts"]["catseqc"] == "catseq._native:run_cli"


def test_native_stub_matches_every_public_pyo3_class_member() -> None:
    stub = ast.parse((ROOT / "catseq/_native.pyi").read_text())
    stub_classes = {
        node.name: {
            member.name
            for member in node.body
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not member.name.startswith("__")
        }
        for node in stub.body
        if isinstance(node, ast.ClassDef)
    }

    for class_name, stub_members in stub_classes.items():
        native_class = getattr(_native, class_name)
        native_members = {
            name for name in native_class.__dict__ if not name.startswith("__")
        }
        assert stub_members == native_members, class_name
