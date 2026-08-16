"""Compiler-only Python surface for the CatSeq sequencing language.

The native compiler parses sequencing source without executing it.  These
objects therefore exist only so modules can be imported and type checkers can
describe the restricted language.  The canonical Morphism and Value
Expression arenas live exclusively in Rust.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import wraps
import sys
from types import FunctionType, ModuleType
from typing import TYPE_CHECKING, Literal, Never, TypeVar, cast, overload

from ..types.common import Channel

if TYPE_CHECKING:
    from ..time_utils import Duration
else:
    Duration = float


class CompilerOnlyError(RuntimeError):
    """Raised when restricted CatSeq source is executed by CPython."""


@dataclass(frozen=True, slots=True)
class CompilerDefinition:
    """Import-time metadata consumed by the registered-source frontend."""

    kind: Literal["atomic_morphism", "morphism"]
    symbol: str | None = None


@dataclass(frozen=True, slots=True)
class _RegisteredDefinition:
    """ARTIQ-style import-time registration for one exact definition."""

    role: Literal[
        "kernel",
        "compute",
        "atomic_morphism",
        "morphism",
        "compiler_intrinsic",
    ]
    symbol: str | None
    original: FunctionType
    wrapper: FunctionType
    module: ModuleType

    def facts(self) -> tuple[object, ...]:
        """Project this registration into the private native bridge schema."""

        return self.original, self.wrapper, self.role, self.symbol, self.module


_DEFINITION_REGISTRY: dict[FunctionType, _RegisteredDefinition] = {}
_REGISTERED_DEFINITIONS: list[_RegisteredDefinition] = []


def compiler_only(symbol: str) -> Never:
    """Reject execution of a source intrinsic by CPython."""

    raise CompilerOnlyError(
        f"{symbol} is a CatSeq compiler intrinsic; analyze the containing "
        "registered source instead of executing it with CPython"
    )


class Morphism:
    """The single nominal sequencing value type in CatSeq source."""

    def __new__(cls, *args: object, **kwargs: object) -> Never:
        del args, kwargs
        compiler_only(cls.__name__)

    @overload
    def __call__(self, target: Channel) -> Morphism: ...

    @overload
    def __call__(self, target: Morphism) -> Morphism: ...

    def __call__(self, target: object, *args: object, **kwargs: object) -> Morphism:
        del target, args, kwargs
        compiler_only("Morphism resource binding")

    @overload
    def __rshift__(self, other: Morphism) -> Morphism: ...

    @overload
    def __rshift__(
        self,
        other: Mapping[Channel, Morphism],
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

    def with_label(self, label: str) -> Morphism:
        del label
        compiler_only("Morphism.with_label")


_F = TypeVar("_F", bound=Callable[..., object])


def _registered_definition(value: object) -> _RegisteredDefinition | None:
    """Return registry authority only for an exact registered function."""

    if type(value) is not FunctionType:
        return None
    return _DEFINITION_REGISTRY.get(value)


def _registered_definition_facts(value: object) -> tuple[object, ...] | None:
    """Project one registry entry into exact built-ins for the native collector."""

    registered = _registered_definition(value)
    if registered is None:
        return None
    return registered.facts()


def _registered_definition_catalog() -> tuple[tuple[object, ...], ...]:
    """Return the current import-time catalog for the native analyzer."""

    return tuple(registered.facts() for registered in _REGISTERED_DEFINITIONS)


def _register_definition(
    definition: _F,
    *,
    role: Literal[
        "kernel",
        "compute",
        "atomic_morphism",
        "morphism",
        "compiler_intrinsic",
    ],
    symbol: str | None = None,
) -> _F:
    if type(definition) is not FunctionType:
        raise TypeError("CatSeq definition decorators require an exact Python function")
    if _registered_definition(definition) is not None:
        raise TypeError("CatSeq definition is already registered with another role")

    original = definition
    module = sys.modules.get(original.__module__)
    if type(module) is not ModuleType:
        raise TypeError("CatSeq definitions must belong to an imported Python module")
    if original.__globals__ is not module.__dict__:
        raise TypeError("CatSeq definitions must use their owning module globals")
    definition_kind = {
        "kernel": "Kernel",
        "compute": "Compute Function",
        "morphism": "Morphism Definition",
        "atomic_morphism": "Atomic Morphism",
        "compiler_intrinsic": "Compiler Intrinsic",
    }[role]
    if role == "kernel":
        execution_remedy = "analyze its BaseExp owner through the registered frontend"
    elif role == "compute":
        execution_remedy = "reference it from registered @kernel or @compute source"
    else:
        execution_remedy = "reference it from registered source"

    @wraps(original)
    def reject_execution(*args: object, **kwargs: object) -> Never:
        del args, kwargs
        raise CompilerOnlyError(
            f"{original.__qualname__} is a compiler-only CatSeq {definition_kind}; "
            f"{execution_remedy} instead of calling it in CPython"
        )

    wrapper = cast(FunctionType, reject_execution)

    if role == "atomic_morphism":
        setattr(
            wrapper,
            "__catseq_definition__",
            CompilerDefinition(kind="atomic_morphism", symbol=symbol),
        )
    elif role == "morphism":
        setattr(
            wrapper,
            "__catseq_definition__",
            CompilerDefinition(kind="morphism"),
        )
    registration = _RegisteredDefinition(
        role=role,
        symbol=symbol,
        original=original,
        wrapper=wrapper,
        module=module,
    )
    _DEFINITION_REGISTRY[original] = registration
    _DEFINITION_REGISTRY[wrapper] = registration
    _REGISTERED_DEFINITIONS.append(registration)
    return wrapper  # type: ignore[return-value]


def kernel(definition: _F) -> _F:
    """Register one compiler-only Kernel definition."""

    return _register_definition(definition, role="kernel")


def compute(definition: _F) -> _F:
    """Register one pure compiler-only Device-time Compute Function."""

    return _register_definition(definition, role="compute")


def morphism(definition: _F) -> _F:
    """Register a restricted source definition that produces a Morphism.

    Like ARTIQ's ``@kernel``, this decorator preserves the original Python
    function so the native compiler can parse its body.  It never builds a
    runtime Morphism arena.
    """

    return _register_definition(definition, role="morphism")


def atomic_morphism(symbol: str) -> Callable[[_F], _F]:
    """Declare a leaf operation implemented by the native Atomic Registry."""

    if type(symbol) is not str:
        raise TypeError("atomic_morphism symbol must be an exact string")
    if not symbol:
        raise ValueError("atomic_morphism symbol must not be empty")

    def decorate(definition: _F) -> _F:
        return _register_definition(
            definition,
            role="atomic_morphism",
            symbol=symbol,
        )

    return decorate


def compiler_intrinsic(symbol: str) -> Callable[[_F], _F]:
    """Register one exact bodyless compiler intrinsic declaration."""

    if type(symbol) is not str:
        raise TypeError("compiler_intrinsic symbol must be an exact string")
    if not symbol:
        raise ValueError("compiler_intrinsic symbol must not be empty")

    def decorate(definition: _F) -> _F:
        return _register_definition(
            definition,
            role="compiler_intrinsic",
            symbol=symbol,
        )

    return decorate


def Id() -> Morphism:
    """Declare the zero-duration Morphism sequencing unit."""

    compiler_only("catseq.morphism.Id")


def Wait(duration: Duration) -> Morphism:
    """Declare a logical cursor displacement with an explicit Duration."""

    del duration
    compiler_only("catseq.morphism.Wait")


def repeat_morphism(morphism: Morphism, count: int) -> Morphism:
    """Declare a native hardware loop without executing or unrolling its body."""

    del morphism, count
    compiler_only("catseq.morphism.repeat_morphism")
