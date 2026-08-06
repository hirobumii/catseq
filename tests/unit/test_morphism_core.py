"""Unit tests for the nominal source types in ``catseq.morphism.core``.

Every operator and constructor on the nominal ``Morphism`` /
``MorphismTemplate`` surface is compiler-only: instantiating or composing them
under CPython must raise ``CompilerOnlyError`` rather than build a runtime IR.
"""

import pytest

from catseq.morphism import (
    CompilerDefinition,
    CompilerOnlyError,
    Morphism,
    MorphismDef,
    MorphismTemplate,
    arena_build,
    atomic_morphism,
    identity,
    morphism_template,
    repeat_morphism,
)
from catseq.morphism.core import compiler_only


def test_compiler_only_raises_with_symbol_and_hint() -> None:
    with pytest.raises(CompilerOnlyError) as excinfo:
        compiler_only("some.symbol")
    message = str(excinfo.value)
    assert "some.symbol" in message
    assert "compile_entry" in message


def test_compiler_only_error_is_a_runtime_error() -> None:
    assert issubclass(CompilerOnlyError, RuntimeError)


class TestMorphismTemplateSurface:
    def test_instantiation_is_compiler_only(self) -> None:
        with pytest.raises(CompilerOnlyError, match="compile_entry"):
            MorphismTemplate()

    def test_binding_is_compiler_only(self) -> None:
        # ``__new__`` itself rejects execution, so exercise the bound behaviour
        # by invoking the unbound method with a placeholder ``self``.
        with pytest.raises(CompilerOnlyError, match="compile_entry"):
            MorphismTemplate.__call__(object(), object())

    @pytest.mark.parametrize(
        "method",
        [
            MorphismTemplate.__rshift__,
            MorphismTemplate.__matmul__,
            MorphismTemplate.__or__,
        ],
    )
    def test_composition_operators_are_compiler_only(self, method) -> None:
        with pytest.raises(CompilerOnlyError, match="compile_entry"):
            method(object(), object())

    def test_with_label_is_compiler_only(self) -> None:
        with pytest.raises(CompilerOnlyError, match="compile_entry"):
            MorphismTemplate.with_label(object(), "label")


class TestMorphismSurface:
    def test_instantiation_is_compiler_only(self) -> None:
        with pytest.raises(CompilerOnlyError, match="compile_entry"):
            Morphism()

    @pytest.mark.parametrize(
        "method",
        [Morphism.__rshift__, Morphism.__matmul__, Morphism.__or__],
    )
    def test_composition_operators_are_compiler_only(self, method) -> None:
        with pytest.raises(CompilerOnlyError, match="compile_entry"):
            method(object(), object())


def test_morphismdef_is_alias_of_morphismtemplate() -> None:
    assert MorphismDef is MorphismTemplate


class TestDecorators:
    def test_morphism_template_preserves_function_and_records_kind(self) -> None:
        def sequence() -> MorphismDef:  # pragma: no cover - body never executed
            raise AssertionError("decorator must not run the source body")

        decorated = morphism_template(sequence)
        assert decorated is sequence
        definition = decorated.__catseq_definition__
        assert isinstance(definition, CompilerDefinition)
        assert definition.kind == "morphism_template"
        assert definition.symbol is None

    def test_atomic_morphism_records_symbol(self) -> None:
        def leaf() -> MorphismDef:  # pragma: no cover - body never executed
            raise AssertionError("decorator must not run the source body")

        decorated = atomic_morphism("catseq.example.leaf")(leaf)
        assert decorated is leaf
        assert decorated.__catseq_definition__.kind == "atomic_morphism"
        assert decorated.__catseq_definition__.symbol == "catseq.example.leaf"

    def test_arena_build_is_an_import_time_noop(self) -> None:
        def sequence() -> Morphism:  # pragma: no cover - body never executed
            raise AssertionError("arena_build must not run the source body")

        assert arena_build(sequence) is sequence


def test_identity_is_compiler_only() -> None:
    with pytest.raises(CompilerOnlyError, match="compile_entry"):
        identity(1.0)


def test_repeat_morphism_is_compiler_only() -> None:
    with pytest.raises(CompilerOnlyError, match="compile_entry"):
        repeat_morphism(object(), 3)


def test_compiler_definition_is_frozen() -> None:
    definition = CompilerDefinition(kind="atomic_morphism", symbol="x")
    with pytest.raises(AttributeError):
        definition.symbol = "y"  # type: ignore[misc]
