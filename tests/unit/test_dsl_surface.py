from importlib import import_module
from inspect import signature
from typing import Any, cast

import pytest

from catseq import replace
from catseq.hardware.common import hold as common_hold
from catseq.hardware.rwg import linear_ramp, load, play, set_state
from catseq.hardware.rsp import (
    initialize as rsp_initialize,
    pid_config,
    pid_hold,
    pid_relink,
    pid_release,
    pid_start,
    rf_config,
)
from catseq.hardware.sync import global_sync
from catseq.hardware.ttl import pulse, set_high
from catseq.morphism import (
    CompilerOnlyError,
    Morphism,
    atomic_morphism,
    identity,
    morphism,
)
from catseq.morphism.core import _registered_definition, compiler_intrinsic
from catseq.time_utils import Duration
from catseq.types import StaticWaveform


def test_identity_is_a_compiler_only_source_intrinsic() -> None:
    with pytest.raises(
        CompilerOnlyError,
        match="registered source",
    ):
        identity(1.0)


def test_replace_is_a_compiler_only_native_record_intrinsic() -> None:
    waveform = StaticWaveform(freq=1.0, amp=0.2)

    with pytest.raises(CompilerOnlyError, match="registered source"):
        replace(waveform, freq=2.0)


def test_black_box_is_a_public_compiler_intrinsic() -> None:
    from catseq.oasm import black_box

    assert tuple(signature(black_box).parameters) == (
        "duration_cycles",
        "board_funcs",
        "user_args",
        "user_kwargs",
        "metadata",
    )
    with pytest.raises(CompilerOnlyError, match="catseq.oasm.black_box"):
        black_box(1, {})


def test_atomic_compatibility_module_is_not_available() -> None:
    with pytest.raises(ModuleNotFoundError, match="catseq.atomic"):
        import_module("catseq.atomic")


def test_hardware_operations_are_compiler_only_source_intrinsics() -> None:
    with pytest.raises(CompilerOnlyError, match="registered source"):
        pulse(1.0)
    with pytest.raises(CompilerOnlyError, match="registered source"):
        pid_relink()


@pytest.mark.parametrize(
    "function",
    [
        common_hold,
        rsp_initialize,
        pid_config,
        pid_start,
        pid_hold,
        pid_release,
        pid_relink,
        rf_config,
        global_sync,
        import_module("catseq.hardware.rwg")._waveforms,
    ],
)
def test_shipped_compiler_intrinsics_have_exact_registration(function: object) -> None:
    registered = _registered_definition(function)

    assert registered is not None
    assert registered.role == "compiler_intrinsic"


def test_morphism_is_a_nominal_source_type_not_a_runtime_ir() -> None:
    with pytest.raises(CompilerOnlyError, match="registered source"):
        Morphism()


def test_public_dsl_exposes_one_morphism_type() -> None:
    catseq_module = import_module("catseq")
    morphism_module = import_module("catseq.morphism")

    assert catseq_module.Morphism is Morphism
    assert morphism_module.Morphism is Morphism
    for legacy_name in ("MorphismDef", "MorphismTemplate", "morphism_template"):
        assert not hasattr(catseq_module, legacy_name)
        assert not hasattr(morphism_module, legacy_name)


def test_user_morphism_definition_keeps_its_python_function_and_compiler_kind() -> None:
    @morphism
    def composite(duration: Duration) -> Morphism:
        return pulse(duration)

    assert composite.__name__ == "composite"
    assert composite.__catseq_definition__.kind == "morphism"
    assert composite.__catseq_definition__.symbol is None


def test_atomic_morphism_declaration_records_its_stable_symbol() -> None:
    @atomic_morphism("example.atomic")
    def atomic() -> Morphism:
        raise AssertionError("the declaration body is irrelevant to this test")

    assert atomic.__catseq_definition__.kind == "atomic_morphism"
    assert atomic.__catseq_definition__.symbol == "example.atomic"


def test_definition_decorators_reject_direct_cpython_execution() -> None:
    executed: list[str] = []
    sentinel = object()

    @morphism
    def composite() -> Morphism:
        executed.append("morphism")
        return cast(Morphism, sentinel)

    @atomic_morphism("example.direct-atomic")
    def atomic() -> Morphism:
        executed.append("atomic")
        return cast(Morphism, sentinel)

    @compiler_intrinsic("example.direct-intrinsic")
    def intrinsic() -> int:
        executed.append("intrinsic")
        return 1

    for definition, role_name in (
        (composite, "Morphism Definition"),
        (atomic, "Atomic Morphism"),
        (intrinsic, "Compiler Intrinsic"),
    ):
        registered = _registered_definition(definition)
        assert registered is not None
        assert registered.original is definition.__wrapped__
        assert registered.wrapper is definition
        with pytest.raises(CompilerOnlyError, match=role_name):
            definition()

    assert executed == []


def test_atomic_morphism_requires_a_non_empty_exact_string_symbol() -> None:
    class Symbol(str):
        pass

    with pytest.raises(TypeError, match="exact string"):
        atomic_morphism(cast(Any, None))
    with pytest.raises(TypeError, match="exact string"):
        atomic_morphism(cast(Any, Symbol("example.atomic")))
    with pytest.raises(ValueError, match="must not be empty"):
        atomic_morphism("")


def test_hardware_api_distinguishes_composite_definitions_from_atomic_leaves() -> None:
    assert pulse.__catseq_definition__.kind == "morphism"
    assert set_state.__catseq_definition__.kind == "morphism"
    assert linear_ramp.__catseq_definition__.kind == "morphism"
    assert load.__catseq_definition__.kind == "atomic_morphism"
    assert load.__catseq_definition__.symbol == "catseq.hardware.rwg.load"
    assert play.__catseq_definition__.kind == "atomic_morphism"
    assert play.__catseq_definition__.symbol == "catseq.hardware.rwg.play"
    assert set_high.__catseq_definition__.kind == "atomic_morphism"
    assert (
        set_high.__catseq_definition__.symbol
        == "catseq.hardware.ttl.set_high"
    )
