from __future__ import annotations

from dataclasses import dataclass
import importlib
from inspect import signature
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, ClassVar, cast

import catseq
import pytest

from catseq.compiler import Compiler
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.params import ExpParam, ExpParams
from catseq.morphism import (
    CompilerDefinition,
    CompilerOnlyError,
    Morphism,
    atomic_morphism,
    morphism_template,
)
from catseq.morphism.core import _registered_definition, kernel


_BODY_CALLS = 0


class _MutableSourceLoader:
    def __init__(self, module_name: str, source: str) -> None:
        self.module_name = module_name
        self.source = source
        self.calls = 0
        self.failure: OSError | None = None

    def get_source(self, fullname: str) -> str:
        assert fullname == self.module_name
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.source


def _loader_source(function_name: str) -> str:
    return f"""\
from catseq.morphism import Morphism
from catseq.morphism.core import kernel

@kernel
def {function_name}() -> Morphism:
    raise AssertionError("registered Kernel bodies must not execute")
"""


def _load_registered_source_module(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    function_name: str,
) -> tuple[ModuleType, _MutableSourceLoader]:
    source = _loader_source(function_name)
    loader = _MutableSourceLoader(module_name, source)
    module = ModuleType(module_name)
    module.__loader__ = loader
    monkeypatch.setitem(sys.modules, module_name, module)
    exec(compile(source, f"<{module_name}>", "exec"), module.__dict__)
    return module, loader


@kernel
def _kernel_helper(width: int) -> Morphism:
    global _BODY_CALLS
    _BODY_CALLS += width
    raise AssertionError("Kernel collection must not execute Python bodies")


_kernel_alias = _kernel_helper


@kernel
def _unused_kernel() -> Morphism:
    global _BODY_CALLS
    _BODY_CALLS += 1
    raise AssertionError("Kernel collection must not execute Python bodies")


@morphism_template
def _morphism_definition(width: int) -> Morphism:
    del width
    raise AssertionError("Kernel collection must not execute Python bodies")


@atomic_morphism("tests.kernel.atomic")
def _atomic_leaf(width: int) -> Morphism:
    del width
    raise AssertionError("Kernel collection must not execute Python bodies")


@dataclass
class _Experiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return _kernel_helper(params[self.width])


@dataclass
class _UndecoratedExperiment(BaseExp):
    def build_sequence(self, params: ExpParams) -> Morphism:
        del params
        raise AssertionError


def _compiler(tmp_path: Path) -> Compiler:
    return Compiler(
        source_root=Path(__file__).parents[2],
        channels={},
        cache_dir=tmp_path / "cache",
    )


def test_kernel_registration_is_private_inert_and_exact_object_authoritative() -> None:
    assert not hasattr(catseq, "kernel")
    assert "kernel" not in catseq.__all__
    assert tuple(signature(_kernel_helper).parameters) == ("width",)

    registered = _registered_definition(_kernel_helper)
    assert registered is not None
    assert registered.role == "kernel"
    assert registered.original is getattr(_kernel_helper, "__wrapped__")
    assert registered.wrapper is _kernel_helper
    assert _registered_definition(_kernel_alias) is registered
    assert not hasattr(_kernel_helper, "__catseq_definition__")

    def fake() -> None:
        pass

    setattr(
        fake,
        "__catseq_definition__",
        CompilerDefinition(kind="morphism_template"),
    )
    assert _registered_definition(fake) is None

    with pytest.raises(CompilerOnlyError, match="compiler-only"):
        _kernel_helper(1)
    assert _BODY_CALLS == 0


def test_collector_keeps_entry_owner_and_registered_definition_catalog(
    tmp_path: Path,
) -> None:
    compiler = _compiler(tmp_path)
    experiment = _Experiment(
        compiler=compiler,
        runtime=object(),
        h5_writer=cast(Any, object()),
    )

    collection = compiler._native._collect_kernel_definitions(experiment)

    assert collection._entry_name == f"{__name__}._Experiment.build_sequence"
    assert collection._entry_owner is experiment
    assert collection._entry_original is getattr(
        _Experiment.build_sequence, "__wrapped__"
    )
    assert collection._entry_wrapper is _Experiment.build_sequence
    names_to_roles = dict(
        zip(collection._definition_names, collection._definition_roles, strict=True)
    )
    assert names_to_roles[f"{__name__}._Experiment.build_sequence"] == "kernel"
    assert names_to_roles[f"{__name__}._kernel_helper"] == "kernel"
    assert names_to_roles[f"{__name__}._unused_kernel"] == "kernel"
    assert names_to_roles[f"{__name__}._morphism_definition"] == "morphism_definition"
    assert names_to_roles[f"{__name__}._atomic_leaf"] == "atomic"
    assert collection._definition_names.count(f"{__name__}._kernel_helper") == 1
    assert "tests.kernel.atomic" in collection._atomic_symbols
    assert _BODY_CALLS == 0


def test_registered_modules_associate_the_exact_entry_with_experiment_source(
    tmp_path: Path,
) -> None:
    compiler = _compiler(tmp_path)
    experiment = _Experiment(
        compiler=compiler,
        runtime=object(),
        h5_writer=cast(Any, object()),
    )

    registered = compiler._native._register_kernel_modules(experiment)

    original = getattr(_Experiment.build_sequence, "__wrapped__")
    locations = {
        name: (file_name, line, column)
        for name, file_name, line, column in registered._definition_locations
    }
    entry_name = f"{__name__}._Experiment.build_sequence"
    assert registered._entry_owner is experiment
    assert registered._entry_original is original
    assert registered._entry_wrapper is _Experiment.build_sequence
    assert entry_name in registered._definition_names
    assert locations[entry_name] == (
        str(Path(__file__).resolve()),
        original.__code__.co_firstlineno,
        5,
    )
    assert "catseq/morphism/core.py" not in locations[entry_name][0]
    assert registered._definition_names.count(f"{__name__}._kernel_helper") == 1
    assert f"{__name__}._unused_kernel" in registered._definition_names
    roles = dict(
        zip(
            registered._definition_names,
            registered._definition_roles,
            strict=True,
        )
    )
    assert roles[f"{__name__}._morphism_definition"] == "morphism_definition"
    assert roles[f"{__name__}._atomic_leaf"] == "atomic"
    assert not any(
        "_UndecoratedExperiment.build_sequence" in name
        for name in registered._definition_names
    )
    assert "tests.kernel.atomic" in registered._atomic_symbols
    with pytest.raises(TypeError):
        type(registered)()
    assert _BODY_CALLS == 0


def test_registered_modules_associate_local_definition_inside_host_control_suite(
    tmp_path: Path,
) -> None:
    with pytest.raises(CompilerOnlyError, match="compiler-only"):

        @kernel
        def control_nested_helper() -> Morphism:
            raise AssertionError("registered Kernel bodies must not execute")

        control_nested_helper()

    experiment = _Experiment(
        compiler=_compiler(tmp_path),
        runtime=object(),
        h5_writer=cast(Any, object()),
    )

    registered = experiment.compiler._native._register_kernel_modules(experiment)

    assert any(
        name.endswith(
            "test_registered_modules_associate_local_definition_inside_host_control_suite."
            "<locals>.control_nested_helper"
        )
        for name in registered._definition_names
    )
    assert _BODY_CALLS == 0


def test_registered_modules_retain_exact_definitions_from_multiple_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "fixtures"))
    fixture = importlib.import_module("kernel_registration_fixture.experiment")
    experiment = fixture.MultiModuleExperiment(
        compiler=_compiler(tmp_path),
        runtime=object(),
        h5_writer=cast(Any, object()),
    )

    registered = experiment.compiler._native._register_kernel_modules(experiment)

    definitions = dict(
        zip(
            registered._definition_names,
            registered._definition_roles,
            strict=True,
        )
    )
    assert (
        definitions[
            "kernel_registration_fixture.experiment."
            "MultiModuleExperiment.build_sequence"
        ]
        == "kernel"
    )
    assert definitions["kernel_registration_fixture.helper.external_helper"] == "kernel"
    assert "kernel_registration_fixture.experiment" in registered._module_names
    assert "kernel_registration_fixture.helper" in registered._module_names


def test_loader_backed_module_is_sourced_once_for_multiple_definitions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = """\
from catseq.morphism import Morphism
from catseq.morphism.core import kernel

@kernel
def first_loader_helper() -> Morphism:
    raise AssertionError("registered Kernel bodies must not execute")

@kernel
def second_loader_helper() -> Morphism:
    raise AssertionError("registered Kernel bodies must not execute")
"""

    class CountingLoader:
        def __init__(self) -> None:
            self.calls = 0

        def get_source(self, fullname: str) -> str:
            assert fullname == "catseq_test_loader_module"
            self.calls += 1
            return source

    loader = CountingLoader()
    module = ModuleType("catseq_test_loader_module")
    module.__loader__ = loader
    monkeypatch.setitem(sys.modules, module.__name__, module)
    exec(compile(source, f"<{module.__name__}>", "exec"), module.__dict__)
    experiment = _Experiment(
        compiler=_compiler(tmp_path),
        runtime=object(),
        h5_writer=cast(Any, object()),
    )

    registered = experiment.compiler._native._register_kernel_modules(experiment)

    assert loader.calls == 1
    assert registered._module_names.count(module.__name__) == 1
    assert f"{module.__name__}.first_loader_helper" in registered._definition_names
    assert f"{module.__name__}.second_loader_helper" in registered._definition_names


def test_distinct_module_objects_are_not_merged_by_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = (
        Path(__file__).parents[1] / "fixtures" / "kernel_registration_same_name.py"
    ).resolve()
    source = source_path.read_text(encoding="utf-8")
    module_name = "catseq_test_same_name_module"

    def load_module() -> ModuleType:
        module = ModuleType(module_name)
        module.__file__ = str(source_path)
        monkeypatch.setitem(sys.modules, module_name, module)
        exec(compile(source, str(source_path), "exec"), module.__dict__)
        return module

    first = load_module()
    second = load_module()
    assert first is not second
    experiment = _Experiment(
        compiler=_compiler(tmp_path),
        runtime=object(),
        h5_writer=cast(Any, object()),
    )

    registered = experiment.compiler._native._register_kernel_modules(experiment)

    assert registered._module_names.count(module_name) == 2
    assert registered._definition_names.count(f"{module_name}.same_name_helper") == 2


def test_module_source_failure_names_the_exact_registered_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "catseq_test_source_failure"
    _, loader = _load_registered_source_module(
        monkeypatch,
        module_name,
        "source_failure_helper",
    )
    loader.failure = OSError("fixture source unavailable")
    experiment = _Experiment(
        compiler=_compiler(tmp_path),
        runtime=object(),
        h5_writer=cast(Any, object()),
    )

    try:
        with pytest.raises(
            RuntimeError,
            match=(
                rf"cannot load registered module {module_name}.*"
                "fixture source unavailable"
            ),
        ):
            experiment.compiler._native._register_kernel_modules(experiment)
    finally:
        loader.failure = None


def test_nac3_parse_failure_retains_loader_module_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "catseq_test_parse_failure"
    _, loader = _load_registered_source_module(
        monkeypatch,
        module_name,
        "parse_failure_helper",
    )
    original_source = loader.source
    loader.source = "@kernel\ndef"
    experiment = _Experiment(
        compiler=_compiler(tmp_path),
        runtime=object(),
        h5_writer=cast(Any, object()),
    )

    try:
        with pytest.raises(
            RuntimeError,
            match=rf"cannot parse registered module {module_name} at <{module_name}>",
        ) as raised:
            experiment.compiler._native._register_kernel_modules(experiment)
        assert f"<{module_name}>:" in str(raised.value)
    finally:
        loader.source = original_source


def test_definition_association_failure_reports_original_source_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "catseq_test_association_failure"
    module, loader = _load_registered_source_module(
        monkeypatch,
        module_name,
        "association_failure_helper",
    )
    original_source = loader.source
    loader.source = original_source.replace(
        "association_failure_helper",
        "renamed_helper",
    )
    original = getattr(module, "association_failure_helper", None)
    assert original is not None
    source_line = original.__wrapped__.__code__.co_firstlineno
    experiment = _Experiment(
        compiler=_compiler(tmp_path),
        runtime=object(),
        h5_writer=cast(Any, object()),
    )

    try:
        with pytest.raises(
            RuntimeError,
            match=(
                rf"registered definition association_failure_helper in module "
                rf"{module_name}.*at <{module_name}>:{source_line}:1"
            ),
        ):
            experiment.compiler._native._register_kernel_modules(experiment)
    finally:
        loader.source = original_source


def test_collector_requires_actual_base_exp_and_registered_entry(
    tmp_path: Path,
) -> None:
    compiler = _compiler(tmp_path)
    undecorated = _UndecoratedExperiment(
        compiler=compiler,
        runtime=object(),
        h5_writer=cast(Any, object()),
    )
    setattr(
        _UndecoratedExperiment.build_sequence,
        "__catseq_definition__",
        CompilerDefinition(kind="morphism_template"),
    )

    with pytest.raises(TypeError, match="registered.*@kernel"):
        compiler._native._collect_kernel_definitions(undecorated)
    with pytest.raises(TypeError, match="BaseExp"):
        compiler._native._collect_kernel_definitions(object())


def test_definition_roles_cannot_be_stacked() -> None:
    with pytest.raises(TypeError, match="already registered"):

        @kernel
        @morphism_template
        def invalid_inner() -> Morphism:
            raise AssertionError

    with pytest.raises(TypeError, match="already registered"):

        @morphism_template
        @kernel
        def invalid_outer() -> Morphism:
            raise AssertionError
