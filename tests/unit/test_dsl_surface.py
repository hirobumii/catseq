from importlib import import_module
from inspect import signature
from typing import Any, cast

import pytest

from catseq import replace
from catseq.hardware.rwg import linear_ramp, load, play, set_state
from catseq.hardware.rsp import pid_relink
from catseq.hardware.ttl import pulse, set_high
from catseq.morphism import (
    CompilerOnlyError,
    Morphism,
    MorphismDef,
    MorphismTemplate,
    atomic_morphism,
    identity,
    morphism_template,
)
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


def test_morphism_is_a_nominal_source_type_not_a_runtime_ir() -> None:
    with pytest.raises(CompilerOnlyError, match="registered source"):
        Morphism()


def test_morphismdef_is_the_source_spelling_of_morphismtemplate() -> None:
    assert MorphismDef is MorphismTemplate


def test_user_morphism_template_keeps_its_python_function_and_compiler_kind() -> None:
    @morphism_template
    def composite(duration: Duration) -> MorphismDef:
        return pulse(duration)

    assert composite.__name__ == "composite"
    assert composite.__catseq_definition__.kind == "morphism_template"
    assert composite.__catseq_definition__.symbol is None


def test_atomic_morphism_declaration_records_its_stable_symbol() -> None:
    @atomic_morphism("example.atomic")
    def atomic() -> MorphismDef:
        raise AssertionError("the declaration body is irrelevant to this test")

    assert atomic.__catseq_definition__.kind == "atomic_morphism"
    assert atomic.__catseq_definition__.symbol == "example.atomic"


def test_atomic_morphism_requires_a_non_empty_exact_string_symbol() -> None:
    class Symbol(str):
        pass

    with pytest.raises(TypeError, match="exact string"):
        atomic_morphism(cast(Any, None))
    with pytest.raises(TypeError, match="exact string"):
        atomic_morphism(cast(Any, Symbol("example.atomic")))
    with pytest.raises(ValueError, match="must not be empty"):
        atomic_morphism("")


def test_hardware_api_distinguishes_composite_templates_from_atomic_leaves() -> None:
    assert pulse.__catseq_definition__.kind == "morphism_template"
    assert set_state.__catseq_definition__.kind == "morphism_template"
    assert linear_ramp.__catseq_definition__.kind == "morphism_template"
    assert load.__catseq_definition__.kind == "atomic_morphism"
    assert load.__catseq_definition__.symbol == "catseq.hardware.rwg.load"
    assert play.__catseq_definition__.kind == "atomic_morphism"
    assert play.__catseq_definition__.symbol == "catseq.hardware.rwg.play"
    assert set_high.__catseq_definition__.kind == "atomic_morphism"
    assert (
        set_high.__catseq_definition__.symbol
        == "catseq.hardware.ttl.set_high"
    )
