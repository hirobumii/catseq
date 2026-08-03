from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import ClassVar

import catseq.experiment
from catseq.compiler import Compiler
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.params import ExpParam, ExpParams
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, identity
from catseq.time_utils import ms
from catseq.types import Board, Channel, ChannelType


EXPERIMENT_DIR = Path(catseq.experiment.__file__).parent
SOURCE_ROOT = Path(__file__).parent

boundary_board = Board("rwg0")
boundary_ttl = Channel(
    boundary_board,
    local_id=0,
    channel_type=ChannelType.TTL,
)


@dataclass
class CompilerBoundaryExperiment(BaseExp):
    duration: ClassVar[ExpParam[float]] = ExpParam("duration_ms", "ms")

    def build_sequence(self, params: ExpParams) -> Morphism:
        return identity(0) >> {boundary_ttl: pulse(params[self.duration] * ms)}


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


def test_compiler_reaches_build_sequence_without_compiling_orchestration(
    tmp_path: Path,
) -> None:
    compiler = Compiler(
        source_root=SOURCE_ROOT,
        channels={"test_dependency_boundaries.boundary_ttl": boundary_ttl},
        cache_dir=tmp_path / "cache",
    )
    experiment = CompilerBoundaryExperiment(
        compiler=compiler,
        runtime=object(),
        h5_writer=object(),
    )

    compiled = compiler.compile(
        experiment.build_sequence,
        ExpParams({experiment.duration: 2.0}),
    )

    assert compiled.logical_duration_cycles == 500_000
    assert not compiled.diagnostics
