from __future__ import annotations

from dataclasses import dataclass
from inspect import signature
from pathlib import Path
from typing import Any, ClassVar, cast

import catseq
import pytest

from catseq.compiler import Compiler
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.params import ExpParam, ExpParams
from catseq.morphism import (
    CompilerOnlyError,
    Morphism,
    atomic_morphism,
    morphism_template,
)
from catseq.morphism.core import _registered_definition, kernel


_BODY_CALLS = 0


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

    def fake() -> None:
        pass

    setattr(
        fake,
        "__catseq_definition__",
        getattr(_kernel_helper, "__catseq_definition__"),
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
        getattr(_kernel_helper, "__catseq_definition__"),
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
