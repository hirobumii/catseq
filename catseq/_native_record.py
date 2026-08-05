"""Compiler-only operations on CatSeq Native Records."""

from typing import TypeVar

from .morphism.core import compiler_only


_T = TypeVar("_T")


def replace(record: _T, /, **changes: object) -> _T:
    """Describe an immutable update of a registered Native Record.

    The Rust frontend validates and lowers this operation. CPython must never
    apply the update because CatSeq Native Records have compiler-owned
    semantics.
    """

    del record, changes
    compiler_only("catseq.replace")
