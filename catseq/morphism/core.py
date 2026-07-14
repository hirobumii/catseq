"""Compiler-only Python surface for the CatSeq sequencing language.

The native compiler parses sequencing source without executing it.  These
objects therefore exist only so modules can be imported and type checkers can
describe the restricted language.  The canonical Morphism and Value
Expression arenas live exclusively in Rust.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Never, ParamSpec, TypeVar, overload

from ..types.common import Channel


class CompilerOnlyError(RuntimeError):
    """Raised when restricted CatSeq source is executed by CPython."""


@dataclass(frozen=True, slots=True)
class CompilerDefinition:
    """Import-time metadata describing how ``catseqc`` treats a definition."""

    kind: Literal["atomic_morphism", "morphism_template"]
    symbol: str | None = None


def compiler_only(symbol: str) -> Never:
    """Reject execution of a source intrinsic outside ``compile_entry``."""

    raise CompilerOnlyError(
        f"{symbol} is a CatSeq compiler intrinsic; pass the containing "
        "sequence method to compile_entry() instead of executing it with CPython"
    )


class MorphismTemplate:
    """Nominal source type for a reusable Morphism with free channel slots."""

    def __new__(cls, *args: object, **kwargs: object) -> Never:
        del args, kwargs
        compiler_only(cls.__name__)

    @overload
    def __call__(self, target: Channel) -> Morphism: ...

    @overload
    def __call__(self, target: Morphism) -> Morphism: ...

    def __call__(self, target: object, *args: object, **kwargs: object) -> Morphism:
        del target, args, kwargs
        compiler_only("MorphismTemplate binding")

    def __rshift__(self, other: MorphismTemplate) -> MorphismTemplate:
        del other
        compiler_only("MorphismTemplate serial composition")

    def __matmul__(self, other: MorphismTemplate) -> MorphismTemplate:
        del other
        compiler_only("MorphismTemplate strict serial composition")

    def __or__(self, other: MorphismTemplate) -> MorphismTemplate:
        del other
        compiler_only("MorphismTemplate parallel composition")

    def with_label(self, label: str) -> MorphismTemplate:
        del label
        compiler_only("MorphismTemplate.with_label")


# Preserve the established source spelling while giving the compiler model an
# honest name.  This is a nominal alias, not a deferred Python generator.
MorphismDef = MorphismTemplate


class Morphism:
    """Nominal source type for a channel-bound sequencing state transformer."""

    def __new__(cls, *args: object, **kwargs: object) -> Never:
        del args, kwargs
        compiler_only(cls.__name__)

    @overload
    def __rshift__(self, other: Morphism) -> Morphism: ...

    @overload
    def __rshift__(
        self,
        other: Mapping[Channel, MorphismTemplate],
    ) -> Morphism: ...

    def __rshift__(self, other: object) -> Morphism:
        del other
        compiler_only("Morphism serial composition")

    def __matmul__(self, other: Morphism) -> Morphism:
        del other
        compiler_only("Morphism strict serial composition")

    def __or__(self, other: Morphism) -> Morphism:
        del other
        compiler_only("Morphism parallel composition")


_P = ParamSpec("_P")
_R = TypeVar("_R")
_F = TypeVar("_F", bound=Callable[..., object])


def morphism_template(definition: _F) -> _F:
    """Mark a restricted Python function as a composable Morphism Template.

    Like ARTIQ's ``@kernel``, this decorator preserves the original Python
    function so the native compiler can parse its body.  It never builds a
    runtime Morphism arena.
    """

    setattr(
        definition,
        "__catseq_definition__",
        CompilerDefinition(kind="morphism_template"),
    )
    return definition


def atomic_morphism(symbol: str) -> Callable[[_F], _F]:
    """Declare a leaf operation implemented by the native Atomic Registry."""

    def decorate(definition: _F) -> _F:
        setattr(
            definition,
            "__catseq_definition__",
            CompilerDefinition(kind="atomic_morphism", symbol=symbol),
        )
        return definition

    return decorate


def arena_build(builder: Callable[_P, _R]) -> Callable[_P, _R]:
    """Retain the legacy decorator spelling as an import-time no-op."""

    return builder


def identity(duration: float | int) -> Morphism:
    """Declare a logical wait; Rust validates and lowers its duration."""

    del duration
    compiler_only("catseq.morphism.identity")


def repeat_morphism(morphism: Morphism, count: int) -> Morphism:
    """Declare a native hardware loop without executing or unrolling its body."""

    del morphism, count
    compiler_only("catseq.morphism.repeat_morphism")
