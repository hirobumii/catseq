from __future__ import annotations

from collections.abc import Callable
from functools import reduce
import inspect
from pathlib import Path

import pytest

from catseq import CatSeqCompileError, Compiler
from catseq.morphism import Morphism, identity, repeat_morphism
from catseq.time_utils import cycles


SOURCE_FOR_GUARD_MESSAGE = "ordinary for specialization is not implemented yet"


@pytest.fixture
def compiler(tmp_path: Path) -> Compiler:
    return Compiler(
        source_root=Path(__file__).parent,
        channels={},
        cache_dir=tmp_path / "cache",
    )


def _assert_source_for_rejected(
    compiler: Compiler,
    entry: Callable[..., object],
    *,
    source_with_for: Callable[..., object] | None = None,
) -> None:
    source = entry if source_with_for is None else source_with_for
    lines, start_line = inspect.getsourcelines(source)
    for offset, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("for "):
            loop_line = start_line + offset
            loop_column = len(line) - len(stripped) + 1
            break
    else:
        raise AssertionError(f"{source.__qualname__} has no source for statement")

    with pytest.raises(CatSeqCompileError) as error:
        compiler.compile(entry)

    expected = (
        f"{Path(__file__).stem}:{loop_line}:{loop_column}: "
        f"{SOURCE_FOR_GUARD_MESSAGE}"
    )
    assert expected in str(error.value)


def selected_source_for(count: int = 3) -> Morphism:
    result = identity(0)
    for _ in range(count):
        result = result >> identity(cycles(4))
    return result


def selected_conditional_source_for() -> Morphism:
    if True:
        for _ in range(3):
            return identity(cycles(4))
    return identity(cycles(1))


def nested_selected_source_for() -> Morphism:
    if True:
        if True:
            for _ in range(3):
                return identity(cycles(4))
    return identity(cycles(1))


def unselected_source_for() -> Morphism:
    if False:
        for _ in range(3):
            return identity(cycles(4))
    return identity(cycles(1))


def nested_unselected_source_for() -> Morphism:
    if False:
        if True:
            for _ in range(3):
                return identity(cycles(4))
    return identity(cycles(1))


def unselected_source_for_with_bad_name() -> Morphism:
    if False:
        for _ in range(3):
            return missing_morphism()  # type: ignore[name-defined]  # noqa: F821
    return identity(cycles(1))


def unselected_source_for_with_bad_type() -> Morphism:
    if False:
        for _ in range(3):
            return identity(cycles("bad"))  # type: ignore[arg-type]
    return identity(cycles(1))


def source_for_helper(count: int = 3) -> Morphism:
    result = identity(0)
    for _ in range(count):
        result = result >> identity(cycles(4))
    return result


def unselected_source_for_call() -> Morphism:
    if False:
        return source_for_helper()
    return identity(cycles(1))


def selected_source_for_call() -> Morphism:
    if True:
        return source_for_helper()
    return identity(cycles(1))


def selected_outer_source_for_call() -> Morphism:
    for _ in range(3):
        return source_for_helper()
    return identity(cycles(1))


def source_for_after_selected_return() -> Morphism:
    return identity(cycles(1))
    for _ in range(3):
        return identity(cycles(4))
    return identity(cycles(4))


def loop_free_selected_return_value() -> Morphism:
    if True:
        return identity(cycles(1))
    return identity(cycles(4))


def source_for_only_helper() -> Morphism:
    for _ in range(3):
        return identity(cycles(4))


def unselected_source_for_only_call() -> Morphism:
    if False:
        return source_for_only_helper()
    return identity(cycles(1))


def selected_source_for_repeat_call() -> Morphism:
    return repeat_morphism(source_for_only_helper(), 2)


def selected_outer_source_for_repeat_call() -> Morphism:
    for _ in range(3):
        return repeat_morphism(source_for_only_helper(), 2)
    return identity(cycles(1))


def unused_lambda_source_for_call() -> Morphism:
    _unused = lambda: source_for_helper()  # noqa: E731
    return identity(cycles(1))


def empty_comprehension_source_for_call() -> Morphism:
    _unused = [source_for_helper() for _ in ()]
    return identity(cycles(1))


def selected_comprehension_source_for_call() -> Morphism:
    _selected = [source_for_helper() for _ in (1,)]
    return identity(cycles(1))


def selected_conditional_comprehension_source_for_call() -> Morphism:
    _selected = [
        source_for_helper() if take else identity(cycles(1)) for take in (True,)
    ]
    return identity(cycles(1))


def filtered_comprehension_source_for_call() -> Morphism:
    _unused = [source_for_helper() for item in (0,) if item > 0]
    return identity(cycles(1))


def selected_bound_intrinsic_comprehension_source_for_call() -> Morphism:
    _selected = [source_for_helper() for item in (1.2,) if round(item) > 0]
    return identity(cycles(1))


def filtered_bound_intrinsic_comprehension_source_for_call() -> Morphism:
    item = (1,)  # noqa: F841 - exercises a stale outer binding in Source HIR
    _unused = [source_for_helper() for item in ((),) if len(item) > 0]
    return identity(cycles(1))


def selected_reduce_lambda_source_for_call() -> Morphism:
    return reduce(
        lambda left, right: left | source_for_helper(),
        [identity(cycles(1)), identity(cycles(2))],
    )


def source_without_native_specialization() -> Morphism:
    pass


def selected_source_without_native_specialization_call() -> Morphism:
    if True:
        return source_without_native_specialization()
    return identity(cycles(1))


class SourceForModule:
    def broken(self) -> Morphism:
        result = identity(0)
        for _ in range(3):
            result = result >> identity(cycles(4))
        return result


source_for_module = SourceForModule()


class SourceForService:
    @property
    def modules(self) -> list[SourceForModule]:
        return [source_for_module]

    def compile(self) -> Morphism:
        _selected = [module.broken() for module in self.modules]
        return identity(cycles(1))


source_for_service = SourceForService()


def test_public_compiler_rejects_a_selected_source_for(compiler: Compiler) -> None:
    _assert_source_for_rejected(compiler, selected_source_for)


def test_public_compiler_rejects_a_conditionally_selected_source_for(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(compiler, selected_conditional_source_for)


def test_public_compiler_rejects_a_nested_selected_source_for(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(compiler, nested_selected_source_for)


def test_public_compiler_ignores_the_guard_on_an_unselected_source_for(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(unselected_source_for)

    assert compiled.logical_duration_cycles == 1


def test_public_compiler_ignores_nested_unselected_source_for(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(nested_unselected_source_for)

    assert compiled.logical_duration_cycles == 1


def test_unselected_source_for_still_reports_name_errors(
    compiler: Compiler,
) -> None:
    with pytest.raises(CatSeqCompileError) as error:
        compiler.compile(unselected_source_for_with_bad_name)

    message = str(error.value)
    assert "reachable Host call test_source_for_guard.missing_morphism" in message
    assert SOURCE_FOR_GUARD_MESSAGE not in message


def test_unselected_source_for_still_reports_type_errors(
    compiler: Compiler,
) -> None:
    with pytest.raises(CatSeqCompileError) as error:
        compiler.compile(unselected_source_for_with_bad_type)

    message = str(error.value)
    assert "expected Int64, found String" in message
    assert SOURCE_FOR_GUARD_MESSAGE not in message


def test_public_compiler_ignores_source_for_in_an_unselected_call(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(unselected_source_for_call)

    assert compiled.logical_duration_cycles == 1


def test_public_compiler_rejects_source_for_in_a_selected_call(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_source_for_call,
        source_with_for=source_for_helper,
    )


def test_selected_outer_source_for_anchor_precedes_its_callee(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(compiler, selected_outer_source_for_call)


def test_public_compiler_ignores_source_for_after_selected_return(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(source_for_after_selected_return)

    assert compiled.logical_duration_cycles == 4


def test_guard_does_not_change_loop_free_value_selection(compiler: Compiler) -> None:
    compiled = compiler.compile(loop_free_selected_return_value)

    assert compiled.logical_duration_cycles == 4


def test_unselected_source_for_call_does_not_require_a_lowered_value(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(unselected_source_for_only_call)

    assert compiled.logical_duration_cycles == 1


def test_selected_source_for_error_precedes_repeat_morphism_lowering(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_source_for_repeat_call,
        source_with_for=source_for_only_helper,
    )


def test_selected_outer_source_for_precedes_repeat_morphism_lowering(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(compiler, selected_outer_source_for_repeat_call)


@pytest.mark.parametrize(
    "entry",
    [
        unused_lambda_source_for_call,
        empty_comprehension_source_for_call,
        filtered_comprehension_source_for_call,
        filtered_bound_intrinsic_comprehension_source_for_call,
    ],
)
def test_deferred_expressions_do_not_select_source_for_calls(
    compiler: Compiler,
    entry: Callable[..., object],
) -> None:
    compiled = compiler.compile(entry)

    assert compiled.logical_duration_cycles == 1


def test_evaluated_comprehension_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_comprehension_source_for_call,
        source_with_for=source_for_helper,
    )


def test_bound_conditional_comprehension_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_conditional_comprehension_source_for_call,
        source_with_for=source_for_helper,
    )


def test_bound_intrinsic_comprehension_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_bound_intrinsic_comprehension_source_for_call,
        source_with_for=source_for_helper,
    )


def test_static_property_comprehension_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        source_for_service.compile,
        source_with_for=SourceForModule.broken,
    )


def test_consumed_reduce_lambda_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_reduce_lambda_source_for_call,
        source_with_for=source_for_helper,
    )


def test_loop_free_missing_specialization_value_still_fails(
    compiler: Compiler,
) -> None:
    with pytest.raises(CatSeqCompileError) as error:
        compiler.compile(selected_source_without_native_specialization_call)

    assert (
        "test_source_for_guard.source_without_native_specialization "
        "does not produce a native specialization value"
    ) in str(error.value)
