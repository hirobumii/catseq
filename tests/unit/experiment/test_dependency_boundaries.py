from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import sys

import catseq.experiment


EXPERIMENT_DIR = Path(catseq.experiment.__file__).parent
def test_non_h5_modules_import_without_h5py() -> None:
    script = f"""
import builtins
import importlib
import pkgutil

real_import = builtins.__import__
def import_without_h5(name, *args, **kwargs):
    if name.split('.', 1)[0] == 'h5py':
        raise ModuleNotFoundError(name)
    return real_import(name, *args, **kwargs)

builtins.__import__ = import_without_h5
for module in pkgutil.iter_modules([{str(EXPERIMENT_DIR)!r}]):
    if module.name != 'h5':
        importlib.import_module(f'catseq.experiment.{{module.name}}')
"""
    subprocess.run([sys.executable, "-c", script], check=True)


def test_h5_and_numpy_imports_stay_in_the_h5_module() -> None:
    for source_path in EXPERIMENT_DIR.glob("*.py"):
        if source_path.name == "h5.py":
            continue
        tree = ast.parse(source_path.read_text())
        imported_roots = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_roots.update(
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert imported_roots.isdisjoint({"h5py", "numpy"}), source_path


def test_experiment_modules_do_not_depend_on_rb1() -> None:
    for source_path in EXPERIMENT_DIR.glob("*.py"):
        tree = ast.parse(source_path.read_text())
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        imports.extend(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not any(name.startswith("rb1system") for name in imports), source_path


def test_no_extra_experiment_layer_was_added() -> None:
    assert not (EXPERIMENT_DIR / "_authoring.py").exists()
