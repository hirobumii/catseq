import pytest

from catseq.hardware.rwg import linear_ramp, load, play, set_state
from catseq.hardware.ttl import pulse, set_high
from catseq.morphism import (
    CompilerOnlyError,
    Morphism,
    MorphismDef,
    MorphismTemplate,
    atomic_morphism,
    arena_build,
    identity,
    morphism_template,
)


def test_identity_is_a_compiler_only_source_intrinsic() -> None:
    with pytest.raises(
        CompilerOnlyError,
        match="compile_entry",
    ):
        identity(1.0)


def test_hardware_operations_are_compiler_only_source_intrinsics() -> None:
    with pytest.raises(CompilerOnlyError, match="compile_entry"):
        pulse(1.0)


def test_morphism_is_a_nominal_source_type_not_a_runtime_ir() -> None:
    with pytest.raises(CompilerOnlyError, match="compile_entry"):
        Morphism()


def test_morphismdef_is_the_source_spelling_of_morphismtemplate() -> None:
    assert MorphismDef is MorphismTemplate


def test_arena_build_is_an_import_time_noop() -> None:
    def sequence() -> Morphism:
        raise AssertionError("the decorator must not execute the source body")

    assert arena_build(sequence) is sequence


def test_user_morphism_template_keeps_its_python_function_and_compiler_kind() -> None:
    @morphism_template
    def composite(duration: float) -> MorphismDef:
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
