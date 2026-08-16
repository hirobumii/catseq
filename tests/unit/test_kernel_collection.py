from __future__ import annotations

import builtins
from dataclasses import dataclass
import importlib
from inspect import signature
from pathlib import Path
import subprocess
import sys
from types import ModuleType
from typing import Any, ClassVar, cast

import catseq
import pytest

from catseq import _native, int32
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.params import ExpParam, ExpParams
from catseq.morphism import (
    CompilerDefinition,
    CompilerOnlyError,
    Morphism,
    atomic_morphism,
    compute,
    identity,
    morphism,
)
from catseq.morphism.core import _registered_definition, kernel
from catseq.time_utils import cycles


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


@compute
def _compute_helper(value: int) -> int:
    global _BODY_CALLS
    _BODY_CALLS += value
    raise AssertionError("Compute collection must not execute Python bodies")


_compute_alias = _compute_helper


@compute
def _compute_twice(value: int) -> int:
    return value * 2


_compute_twice_alias = _compute_twice


@compute
def _compute_normalize(value: int) -> int:
    return _compute_twice(value) + _compute_twice_alias(value) + 1


_compute_normalize_alias = _compute_normalize


@compute
def _compute_bounded_fold(value: int) -> int:
    result = value
    for _ in range(4):
        result = (result * 3 + 1) // 4
    return result


@compute
def _compute_is_negative(value: int) -> bool:
    return value < 0


@compute
def _compute_explicit_int32(value: int32) -> int32:
    return value + 1


@compute
def _compute_float(value: int) -> float:
    return value / 2.0


@compute
def _compute_transitive_float(value: int) -> int:
    return _compute_float(value)


@kernel
def _unused_kernel() -> Morphism:
    global _BODY_CALLS
    _BODY_CALLS += 1
    raise AssertionError("Kernel collection must not execute Python bodies")


@morphism
def _morphism_definition(width: int) -> Morphism:
    del width
    raise AssertionError("Kernel collection must not execute Python bodies")


@atomic_morphism("tests.kernel.atomic")
def _atomic_leaf(width: int) -> Morphism:
    del width
    raise AssertionError("Kernel collection must not execute Python bodies")


def _host_scalar(value: int) -> int:
    return value + 1


class _ComputeRecord:
    def __init__(self, value: int) -> None:
        self.value = value


_COMPUTE_FLOAT_AMBIENT = 0.5
_COMPUTE_INT_AMBIENT = 2


@compute
def _compute_calls_kernel(value: int) -> int:
    _kernel_helper(value)
    return value


@compute
def _compute_calls_morphism(value: int) -> int:
    _morphism_definition(value)
    return value


@compute
def _compute_calls_atomic(value: int) -> int:
    _atomic_leaf(value)
    return value


@compute
def _compute_calls_host(value: int) -> int:
    return _host_scalar(value)


@compute
def _compute_calls_constructor(value: int) -> int:
    record = _ComputeRecord(value)
    return record.value


@compute
def _compute_reads_float_ambient(value: int) -> int:
    _ = _COMPUTE_FLOAT_AMBIENT
    return value


@compute
def _compute_reads_int_ambient(value: int) -> int:
    _ = _COMPUTE_INT_AMBIENT
    return value


@compute
def _compute_mutates_ambient(value: int) -> int:
    global _BODY_CALLS
    _BODY_CALLS += value
    return value


@dataclass
class _Experiment(BaseExp):
    width: ClassVar[ExpParam[int]] = ExpParam("width")

    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return _kernel_helper(params[self.width])


@dataclass
class _SimpleAnalysisExperiment(BaseExp):
    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return identity(cycles(1))


@dataclass
class _UndecoratedExperiment(BaseExp):
    def build_sequence(self, params: ExpParams) -> Morphism:
        del params
        raise AssertionError


def test_kernel_registration_is_public_inert_and_exact_object_authoritative() -> None:
    assert catseq.kernel is kernel
    assert "kernel" in catseq.__all__
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
        CompilerDefinition(kind="morphism"),
    )
    assert _registered_definition(fake) is None

    with pytest.raises(CompilerOnlyError, match="compiler-only"):
        _kernel_helper(1)
    assert _BODY_CALLS == 0


def test_compute_registration_is_public_inert_and_exact_object_authoritative() -> None:
    assert catseq.compute is compute
    assert catseq.int32 is int
    assert "compute" in catseq.__all__
    assert tuple(signature(_compute_helper).parameters) == ("value",)

    registered = _registered_definition(_compute_helper)
    assert registered is not None
    assert registered.role == "compute"
    assert registered.original is getattr(_compute_helper, "__wrapped__")
    assert registered.wrapper is _compute_helper
    assert _registered_definition(_compute_alias) is registered
    assert not hasattr(_compute_helper, "__catseq_definition__")

    with pytest.raises(CompilerOnlyError, match="compiler-only CatSeq Compute Function"):
        _compute_helper(1)
    assert _BODY_CALLS == 0


def test_collector_keeps_entry_owner_and_registered_definition_catalog(
    tmp_path: Path,
) -> None:
    experiment = _Experiment(
        h5_writer=cast(Any, object()),
    )

    collection = _native._collect_kernel_definitions(experiment)

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
    assert names_to_roles[f"{__name__}._compute_helper"] == "compute"
    assert names_to_roles[f"{__name__}._unused_kernel"] == "kernel"
    assert names_to_roles[f"{__name__}._morphism_definition"] == "morphism_definition"
    assert names_to_roles[f"{__name__}._atomic_leaf"] == "atomic"
    assert collection._definition_names.count(f"{__name__}._kernel_helper") == 1
    assert "tests.kernel.atomic" in collection._atomic_symbols
    assert _BODY_CALLS == 0


def test_registered_modules_associate_the_exact_entry_with_experiment_source(
    tmp_path: Path,
) -> None:
    experiment = _Experiment(
        h5_writer=cast(Any, object()),
    )

    registered = _native._register_kernel_modules(experiment)

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
    assert roles[f"{__name__}._compute_helper"] == "compute"
    assert roles[f"{__name__}._atomic_leaf"] == "atomic"
    assert not any(
        "_UndecoratedExperiment.build_sequence" in name
        for name in registered._definition_names
    )
    assert "tests.kernel.atomic" in registered._atomic_symbols
    with pytest.raises(TypeError):
        type(registered)()
    assert _BODY_CALLS == 0


def test_registered_modules_validate_exact_compute_roots_and_transitive_aliases(
    tmp_path: Path,
) -> None:
    experiment = _Experiment(
        h5_writer=cast(Any, object()),
    )
    registered = _native._register_kernel_modules(experiment)

    validation = registered._validate_compute_roots((_compute_normalize_alias,))
    names = registered._definition_names
    interface_names = [
        names[definition_id] for definition_id in validation._interface_definition_ids
    ]
    assert interface_names == [
        f"{__name__}._compute_twice",
        f"{__name__}._compute_normalize",
    ]
    assert validation._source_profile_id == "catseq-int32-v1"
    assert validation._interface_parameters == [["i32"], ["i32"]]
    assert validation._interface_results == ["i32", "i32"]
    assert validation._abi_signatures == ["(i32)->i32", "(i32)->i32"]
    assert all(len(abi_hash) == 64 for abi_hash in validation._abi_hashes)
    assert all(
        module == __name__ and file_name == str(Path(__file__).resolve())
        for module, file_name, _, _ in validation._provenance
    )
    assert validation._unit_count == 2
    assert validation._source_unit_count == 1
    assert not hasattr(validation, "__dict__")
    original = getattr(_compute_normalize, "__wrapped__")
    assert registered._validate_compute_roots((original,))._unit_count == 2
    explicit_int32 = registered._validate_compute_roots((_compute_explicit_int32,))
    assert explicit_int32._abi_signatures == ["(i32)->i32"]


def test_compute_validation_rejects_fake_rebound_and_atomic_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = _Experiment(
        h5_writer=cast(Any, object()),
    )
    registered = _native._register_kernel_modules(experiment)

    def fake_compute(value: int) -> int:
        return value

    fake_compute.__catseq_definition__ = "compute"  # type: ignore[attr-defined]
    with pytest.raises(TypeError, match="exact @compute identity"):
        registered._validate_compute_roots((fake_compute,))

    def ordinary_helper(value: int) -> int:
        return value

    with pytest.raises(TypeError, match="exact @compute identity"):
        registered._validate_compute_roots((ordinary_helper,))

    with pytest.raises(RuntimeError, match="not admitted by CatSeqInt32V1"):
        registered._validate_compute_roots((_compute_normalize, _compute_float))
    with pytest.raises(RuntimeError, match="not admitted by CatSeqInt32V1"):
        registered._validate_compute_roots((_compute_transitive_float,))
    assert registered._validate_compute_roots((_compute_normalize,))._unit_count == 2

    monkeypatch.setattr(sys.modules[__name__], "_compute_twice", fake_compute)
    assert registered._validate_compute_roots((_compute_normalize,))._unit_count == 2

    rebound_session = _native._register_kernel_modules(experiment)
    with pytest.raises(RuntimeError, match="Host RPC or dynamic callee"):
        rebound_session._validate_compute_roots((_compute_normalize,))


@pytest.mark.parametrize(
    ("root", "message"),
    [
        (_compute_calls_kernel, "Kernel"),
        (_compute_calls_morphism, "Morphism"),
        (_compute_calls_atomic, "Atomic"),
        (_compute_calls_host, "Host RPC or dynamic callee"),
        (_compute_calls_constructor, "Host RPC or dynamic callee"),
        (_compute_reads_float_ambient, "ambient Compute value"),
        (_compute_reads_int_ambient, "ambient Compute value"),
        (_compute_mutates_ambient, "unsupported or effectful statement"),
    ],
)
def test_compute_validation_rejects_actual_cross_domain_objects(
    tmp_path: Path,
    root: object,
    message: str,
) -> None:
    experiment = _Experiment(
        h5_writer=cast(Any, object()),
    )
    registered = _native._register_kernel_modules(experiment)

    with pytest.raises(RuntimeError, match=message):
        registered._validate_compute_roots((root,))
    assert registered._validate_compute_roots((_compute_normalize,))._unit_count == 2


def test_compute_validation_respects_shadowing_of_the_range_intrinsic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = _Experiment(
        h5_writer=cast(Any, object()),
    )
    registered = _native._register_kernel_modules(experiment)

    assert registered._validate_compute_roots((_compute_bounded_fold,))._unit_count == 1

    def host_range(stop: int) -> range:
        return range(stop)

    monkeypatch.setattr(sys.modules[__name__], "range", host_range, raising=False)
    assert registered._validate_compute_roots((_compute_bounded_fold,))._unit_count == 1

    shadowed_session = _native._register_kernel_modules(experiment)
    with pytest.raises(RuntimeError, match="range.*shadowed"):
        shadowed_session._validate_compute_roots((_compute_bounded_fold,))


@pytest.mark.parametrize(
    ("name", "root"),
    [
        ("int", _compute_normalize),
        ("int32", _compute_explicit_int32),
        ("bool", _compute_is_negative),
    ],
)
def test_compute_validation_freezes_exact_builtin_type_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    root: object,
) -> None:
    experiment = _Experiment(
        h5_writer=cast(Any, object()),
    )
    registered = _native._register_kernel_modules(experiment)

    monkeypatch.setattr(sys.modules[__name__], name, object(), raising=False)
    assert registered._validate_compute_roots((root,))._unit_count >= 1

    rebound_session = _native._register_kernel_modules(experiment)
    with pytest.raises(RuntimeError, match=rf"builtin `{name}` is shadowed"):
        rebound_session._validate_compute_roots((root,))


def test_compute_validation_uses_cpython_builtin_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical_range = range

    def replacement_range(*args: int) -> object:
        return canonical_range(*args)

    monkeypatch.setattr(builtins, "range", replacement_range)
    experiment = _Experiment(
        h5_writer=cast(Any, object()),
    )
    registered = _native._register_kernel_modules(experiment)

    with pytest.raises(RuntimeError, match="builtin `range` is shadowed"):
        registered._validate_compute_roots((_compute_bounded_fold,))


def test_compute_validation_uses_the_module_builtin_namespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "catseq_test_custom_builtins"
    source = """\
from catseq.morphism import compute

@compute
def custom_compute(value: int) -> int:
    return value
"""
    loader = _MutableSourceLoader(module_name, source)
    module = ModuleType(module_name)
    module.__loader__ = loader
    custom_builtins = vars(builtins).copy()
    custom_builtins["int"] = object()
    module.__dict__["__builtins__"] = custom_builtins
    monkeypatch.setitem(sys.modules, module_name, module)
    exec(compile(source, f"<{module_name}>", "exec"), module.__dict__)

    experiment = _Experiment(
        h5_writer=cast(Any, object()),
    )
    registered = _native._register_kernel_modules(experiment)

    with pytest.raises(RuntimeError, match="builtin `int` is shadowed"):
        registered._validate_compute_roots((module.custom_compute,))


def test_compute_validation_uses_the_function_builtin_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "catseq_test_rebound_builtins"
    source = """\
from catseq.morphism import compute

@compute
def custom_compute(value: int) -> int:
    total = 0
    for _ in range(2):
        total += value
    return total
"""
    loader = _MutableSourceLoader(module_name, source)
    module = ModuleType(module_name)
    module.__loader__ = loader
    function_builtins = vars(builtins).copy()
    function_builtins["range"] = object()
    module.__dict__["__builtins__"] = function_builtins
    monkeypatch.setitem(sys.modules, module_name, module)
    exec(compile(source, f"<{module_name}>", "exec"), module.__dict__)
    module.__dict__["__builtins__"] = vars(builtins)

    experiment = _Experiment(
        h5_writer=cast(Any, object()),
    )
    registered = _native._register_kernel_modules(experiment)

    with pytest.raises(RuntimeError, match="builtin `range` is shadowed"):
        registered._validate_compute_roots((module.custom_compute,))


def test_compute_decorator_rejects_foreign_globals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "catseq_test_foreign_compute_globals"
    source = """\
from catseq.morphism import compute

@compute
def misplaced(value: int) -> int:
    return value
"""
    module = ModuleType(module_name)
    monkeypatch.setitem(sys.modules, module_name, module)
    foreign_globals = {
        "__name__": module_name,
        "__builtins__": vars(builtins),
    }

    with pytest.raises(TypeError, match="owning module globals"):
        exec(compile(source, f"<{module_name}>", "exec"), foreign_globals)


def test_in_place_reload_cannot_rebind_an_old_compute_identity(
    tmp_path: Path,
) -> None:
    script = """\
from dataclasses import dataclass
from pathlib import Path
import sys
from types import ModuleType

from catseq import _native
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.params import ExpParams
from catseq.morphism import Morphism
from catseq.morphism.core import kernel


class Loader:
    def __init__(self, name, source):
        self.name = name
        self.source = source

    def get_source(self, fullname):
        assert fullname == self.name
        return self.source


module_name = "catseq_test_in_place_reload"
old_source = '''from catseq.morphism import compute

@compute
def normalize(value: int) -> int:
    return value / 2.0
'''
new_source = '''from catseq.morphism import compute

@compute
def normalize(value: int) -> int:
    return value + 1
'''
loader = Loader(module_name, old_source)
module = ModuleType(module_name)
module.__loader__ = loader
sys.modules[module_name] = module
exec(compile(old_source, f"<{module_name}>", "exec"), module.__dict__)
old_identity = module.normalize
loader.source = new_source
exec(compile(new_source, f"<{module_name}>", "exec"), module.__dict__)
assert old_identity is not module.normalize


@dataclass
class Experiment(BaseExp):
    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        del params
        raise AssertionError


experiment = Experiment(h5_writer=object())
try:
    _native._register_kernel_modules(experiment)
except RuntimeError as error:
    assert "refer to the same source definition" in str(error), error
else:
    raise AssertionError("in-place reload identities shared one frozen AST")
"""
    script_path = tmp_path / "reload_regression.py"
    script_path.write_text(script, encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_registered_modules_associate_local_definition_inside_host_control_suite(
    tmp_path: Path,
) -> None:
    with pytest.raises(CompilerOnlyError, match="compiler-only"):

        @kernel
        def control_nested_helper() -> Morphism:
            raise AssertionError("registered Kernel bodies must not execute")

        control_nested_helper()

    experiment = _Experiment(
        h5_writer=cast(Any, object()),
    )

    registered = _native._register_kernel_modules(experiment)

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
        h5_writer=cast(Any, object()),
    )

    registered = _native._register_kernel_modules(experiment)

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
    validation = registered._validate_compute_roots((fixture.external_normalize,))
    interface_names = [
        registered._definition_names[definition_id]
        for definition_id in validation._interface_definition_ids
    ]
    assert interface_names == [
        "kernel_registration_fixture.helper.external_twice",
        "kernel_registration_fixture.experiment.external_normalize",
    ]
    assert validation._source_unit_count == 2

    direct_external = registered._validate_compute_roots((fixture.external_twice,))
    assert direct_external._unit_count == 1
    attribute_validation = registered._validate_compute_roots(
        (fixture.external_attribute_normalize,)
    )
    attribute_interface_names = [
        registered._definition_names[definition_id]
        for definition_id in attribute_validation._interface_definition_ids
    ]
    assert attribute_interface_names == [
        "kernel_registration_fixture.helper.external_twice",
        "kernel_registration_fixture.experiment.external_attribute_normalize",
    ]


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
        h5_writer=cast(Any, object()),
    )

    registered = _native._register_kernel_modules(experiment)

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
        h5_writer=cast(Any, object()),
    )

    registered = _native._register_kernel_modules(experiment)

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
            _native._register_kernel_modules(experiment)
    finally:
        loader.failure = None


def test_entry_analysis_ignores_unreferenced_registered_module_source_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "catseq_test_unreferenced_source_failure"
    _, loader = _load_registered_source_module(
        monkeypatch,
        module_name,
        "unreferenced_source_failure_helper",
    )
    loader.failure = OSError("unreferenced fixture source unavailable")
    experiment = _SimpleAnalysisExperiment(
        h5_writer=cast(Any, object()),
    )

    try:
        analysis = _native._FrontendSession({})._analyze_registered_kernel(
            experiment,
            ExpParams({}),
        )
        assert (
            analysis._entry_name
            == f"{__name__}._SimpleAnalysisExperiment.build_sequence"
        )
        assert f"{module_name}.unreferenced_source_failure_helper" not in dict(
            analysis._body_definitions
        )
    finally:
        loader.failure = None


def test_entry_analysis_rejects_source_that_no_longer_matches_registered_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "catseq_test_stale_registered_source"
    original_source = """\
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.params import ExpParams
from catseq.morphism import Morphism, identity
from catseq.morphism.core import kernel
from catseq.time_utils import cycles

class SnapshotExperiment(BaseExp):
    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return identity(cycles(1))
"""
    changed_source = original_source.replace("cycles(1)", "cycles(2)")
    loader = _MutableSourceLoader(module_name, original_source)
    module = ModuleType(module_name)
    module.__loader__ = loader
    monkeypatch.setitem(sys.modules, module_name, module)
    exec(compile(original_source, f"<{module_name}>", "exec"), module.__dict__)
    experiment = module.SnapshotExperiment(h5_writer=cast(Any, object()))
    loader.source = changed_source

    try:
        with pytest.raises(
            RuntimeError,
            match=(
                rf"registered definition {module_name}\.SnapshotExperiment\.build_sequence "
                rf"does not match the source revision at <{module_name}>"
            ),
        ):
            _native._FrontendSession({})._analyze_registered_kernel(
                experiment,
                ExpParams({}),
            )
    finally:
        loader.source = original_source


@pytest.mark.parametrize(
    ("case", "changed_source_fragment", "mismatch"),
    [
        ("default", "width: int = 2", "positional defaults"),
        ("annotation", "width: bool = 1", "annotations"),
    ],
)
def test_entry_analysis_rejects_source_signature_revision_drift(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    changed_source_fragment: str,
    mismatch: str,
) -> None:
    module_name = f"catseq_test_stale_registered_signature_{case}"
    original_source = """\
from __future__ import annotations

from catseq.experiment.base_exp import BaseExp
from catseq.experiment.params import ExpParams
from catseq.morphism import Morphism, identity, morphism
from catseq.morphism.core import kernel
from catseq.time_utils import cycles

@morphism
def configured(width: int = 1) -> Morphism:
    return identity(cycles(width))

class SnapshotExperiment(BaseExp):
    @kernel
    def build_sequence(self, params: ExpParams) -> Morphism:
        return configured()
"""
    changed_source = original_source.replace("width: int = 1", changed_source_fragment)
    loader = _MutableSourceLoader(module_name, original_source)
    module = ModuleType(module_name)
    module.__loader__ = loader
    monkeypatch.setitem(sys.modules, module_name, module)
    exec(compile(original_source, f"<{module_name}>", "exec"), module.__dict__)
    experiment = module.SnapshotExperiment(h5_writer=cast(Any, object()))
    loader.source = changed_source

    try:
        with pytest.raises(
            RuntimeError,
            match=(
                rf"registered definition {module_name}\.configured "
                rf"does not match the source revision at <{module_name}>.*\({mismatch}\)"
            ),
        ):
            _native._FrontendSession({})._analyze_registered_kernel(
                experiment,
                ExpParams({}),
            )
    finally:
        loader.source = original_source


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
        h5_writer=cast(Any, object()),
    )

    try:
        with pytest.raises(
            RuntimeError,
            match=rf"cannot parse registered module {module_name} at <{module_name}>",
        ) as raised:
            _native._register_kernel_modules(experiment)
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
            _native._register_kernel_modules(experiment)
    finally:
        loader.source = original_source


def test_collector_requires_actual_base_exp_and_registered_entry(
    tmp_path: Path,
) -> None:
    undecorated = _UndecoratedExperiment(
        h5_writer=cast(Any, object()),
    )
    setattr(
        _UndecoratedExperiment.build_sequence,
        "__catseq_definition__",
        CompilerDefinition(kind="morphism"),
    )

    with pytest.raises(TypeError, match="registered.*@kernel"):
        _native._collect_kernel_definitions(undecorated)
    with pytest.raises(TypeError, match="BaseExp"):
        _native._collect_kernel_definitions(object())


def test_definition_roles_cannot_be_stacked() -> None:
    with pytest.raises(TypeError, match="already registered"):

        @kernel
        @morphism
        def invalid_inner() -> Morphism:
            raise AssertionError

    with pytest.raises(TypeError, match="already registered"):

        @morphism
        @kernel
        def invalid_outer() -> Morphism:
            raise AssertionError

    with pytest.raises(TypeError, match="already registered"):

        @compute
        @kernel
        def invalid_compute_inner(value: int) -> int:
            return value

    with pytest.raises(TypeError, match="already registered"):

        @kernel
        @compute
        def invalid_compute_outer(value: int) -> Morphism:
            del value
            raise AssertionError
