import ast
import inspect
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


def test_native_stub_matches_the_complete_public_pyo3_surface() -> None:
    stub = ast.parse((ROOT / "catseq/_native.pyi").read_text())
    stub_functions = {
        node.name: [argument.arg for argument in (*node.args.posonlyargs, *node.args.args)]
        for node in stub.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }
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
    stub_public = set(stub_functions) | set(stub_classes)
    native_public = {
        name for name in _native.__dict__ if not name.startswith("_")
    }

    assert stub_public == native_public

    for function_name, stub_parameters in stub_functions.items():
        native_parameters = list(inspect.signature(getattr(_native, function_name)).parameters)
        assert stub_parameters == native_parameters, function_name

    for class_name, stub_members in stub_classes.items():
        native_class = getattr(_native, class_name)
        native_members = {
            name for name in native_class.__dict__ if not name.startswith("__")
        }
        assert stub_members == native_members, class_name

        init = next(
            (
                node
                for node in stub.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            ),
            None,
        )
        assert init is not None
        stub_init = next(
            (
                member
                for member in init.body
                if isinstance(member, ast.FunctionDef) and member.name == "__init__"
            ),
            None,
        )
        if stub_init is None:
            continue
        stub_parameters = [
            argument.arg
            for argument in (*stub_init.args.posonlyargs, *stub_init.args.args)
            if argument.arg != "self"
        ]
        native_parameters = list(inspect.signature(native_class).parameters)
        assert stub_parameters == native_parameters, class_name
