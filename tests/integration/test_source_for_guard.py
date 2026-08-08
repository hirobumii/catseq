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


def selected_rebound_nested_if_source_for() -> Morphism:
    selected = False
    if True:
        selected = True
        if selected:
            for _ in range(3):
                return identity(cycles(4))
    return identity(cycles(1))


def identity_bool(selected: bool) -> bool:
    return selected


def selected_named_expression_call_result_source_for() -> Morphism:
    selected = False
    _ = (selected := True)
    if identity_bool(selected):
        for _ in range(3):
            return identity(cycles(4))
    return identity(cycles(1))


def unselected_named_expression_call_result_source_for() -> Morphism:
    selected = True
    _ = (selected := False)
    if identity_bool(selected):
        for _ in range(3):
            return identity(cycles(4))
    return identity(cycles(1))


def selected_augmented_rebound_source_for() -> Morphism:
    count = 1
    count += 1
    if count == 2:
        for _ in range(3):
            return identity(cycles(4))
    return identity(cycles(1))


def selected_named_expression_rebound_source_for() -> Morphism:
    selected = False
    _ = (selected := True)
    if selected:
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


def source_for_bool() -> bool:
    for _ in range(1):
        return True
    return False


def source_for_bool_only() -> bool:
    for _ in range(1):
        return True


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


def loop_free_boolean_conditional_value() -> Morphism:
    return identity(cycles(1)) if False or True else identity(cycles(4))


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


def selected_comprehension_named_expression_rebound_source_for() -> Morphism:
    selected = False
    _unused = [(selected := True) for _item in (1,)]
    if selected:
        for _ in range(1):
            return identity(cycles(4))
    return identity(cycles(1))


def comprehension_target_does_not_rebind_outer_guard() -> Morphism:
    selected = False
    _unused = [selected for selected in (True,)]
    if selected:
        for _ in range(1):
            return identity(cycles(4))
    return identity(cycles(1))


def selected_multi_generator_comprehension_source_for_call() -> Morphism:
    _selected = [
        source_for_helper() for left in (1,) for right in (1,) if left == right
    ]
    return identity(cycles(1))


def selected_dictionary_comprehension_source_for_call() -> Morphism:
    _selected = {key: source_for_helper() for key in (1,)}
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


def conditional_source_for(selected: bool = True) -> Morphism:
    if selected:
        return source_for_helper()
    return identity(cycles(1))


def selected_bound_argument_comprehension_source_for_call() -> Morphism:
    _selected = [conditional_source_for(selected) for selected in (True,)]
    return identity(cycles(1))


def unselected_bound_argument_comprehension_source_for_call() -> Morphism:
    _unused = [conditional_source_for(selected) for selected in (False,)]
    return identity(cycles(1))


def selected_boolean_conditional_argument_source_for_call() -> Morphism:
    return conditional_source_for(True if False or True else False)


def unselected_boolean_conditional_argument_source_for_call() -> Morphism:
    return conditional_source_for(False if False or True else True)


def positional_guard_probe(
    unavailable: bool,
    selected: bool = False,
) -> Morphism:
    if selected:
        return source_for_helper()
    return identity(cycles(1))


def comprehension_with_unavailable_positional_before_bound_guard() -> Morphism:
    _selected = [
        positional_guard_probe(selected and True, selected) for selected in (True,)
    ]
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


def selected_reduce_lambda_alias_source_for_call() -> Morphism:
    combine = lambda left, right: left | source_for_helper()  # noqa: E731
    return reduce(
        combine,
        [identity(cycles(1)), identity(cycles(2))],
    )


def named_source_for_reducer(left: Morphism, right: Morphism) -> Morphism:
    return left | right | source_for_helper()


def selected_named_reduce_source_for_call() -> Morphism:
    return reduce(
        named_source_for_reducer,
        [identity(cycles(1)), identity(cycles(2))],
    )


def return_left_source_for_reducer(left: Morphism, right: Morphism) -> Morphism:
    if left is right:
        for _ in range(1):
            return left
    return left


def selected_return_left_reduce_source_for_call() -> Morphism:
    first = identity(cycles(1))
    second = identity(cycles(2))
    return reduce(return_left_source_for_reducer, (first, second, first))


def unselected_return_left_reduce_source_for_call() -> Morphism:
    first = identity(cycles(1))
    second = identity(cycles(1))
    return reduce(return_left_source_for_reducer, (first, second, second))


def loop_free_named_reducer(left: Morphism, right: Morphism) -> Morphism:
    return left | right


def direct_source_for_named_reducer(left: Morphism, right: Morphism) -> Morphism:
    for _ in range(1):
        return left | right
    return left | right


def selected_conditional_named_reduce_source_for_call() -> Morphism:
    return reduce(
        direct_source_for_named_reducer if True else loop_free_named_reducer,
        [identity(cycles(1)), identity(cycles(2))],
    )


def unselected_conditional_named_reduce_source_for_call() -> Morphism:
    return reduce(
        loop_free_named_reducer if True else direct_source_for_named_reducer,
        [identity(cycles(1)), identity(cycles(2))],
    )


def selected_conditional_reduce_lambda_source_for_call() -> Morphism:
    return reduce(
        (lambda left, right: left | right | source_for_helper())
        if True
        else (lambda left, right: left | right),
        [identity(cycles(1)), identity(cycles(2))],
    )


def selected_bound_reduce_parameter_source_for_call() -> Morphism:
    return reduce(
        lambda left, right: left
        | (source_for_helper() if right else identity(cycles(1))),
        [identity(cycles(1)), identity(cycles(2))],
    )


def initialized_single_item_reduce_lambda_source_for_call() -> Morphism:
    return reduce(
        lambda left, right: left | source_for_helper(),
        [identity(cycles(1))],
        identity(0),
    )


def uninitialized_single_item_reduce_lambda_source_for_call() -> Morphism:
    return reduce(
        lambda left, right: left | source_for_helper(),
        [identity(cycles(1))],
    )


def initialized_empty_reduce_lambda_source_for_call() -> Morphism:
    return reduce(
        lambda left, right: left | source_for_helper(),
        [],
        identity(0),
    )


def short_circuited_and_source_for_call() -> Morphism:
    _unused = False and source_for_bool()
    return identity(cycles(1))


def short_circuited_or_source_for_call() -> Morphism:
    _unused = True or source_for_bool()
    return identity(cycles(1))


def short_circuited_zero_and_source_for_call() -> Morphism:
    _unused = 0 and source_for_bool()
    return identity(cycles(1))


def short_circuited_one_or_source_for_call() -> Morphism:
    _unused = 1 or source_for_bool()
    return identity(cycles(1))


def nested_short_circuited_and_source_for_call() -> Morphism:
    _unused = (False or False) and source_for_bool()
    return identity(cycles(1))


def nested_short_circuited_or_source_for_call() -> Morphism:
    _unused = (True and True) or source_for_bool()
    return identity(cycles(1))


def selected_and_source_for_call() -> Morphism:
    _selected = True and source_for_bool()
    return identity(cycles(1))


def selected_or_source_for_call() -> Morphism:
    _selected = False or source_for_bool()
    return identity(cycles(1))


def short_circuited_comparison_source_for_call() -> Morphism:
    _unused = False == True == source_for_bool()  # noqa: E712
    return identity(cycles(1))


def selected_comparison_source_for_call() -> Morphism:
    _selected = True == True == source_for_bool()  # noqa: E712
    return identity(cycles(1))


def selected_boolean_conditional_source_for_call() -> Morphism:
    _selected = source_for_bool() if False or True else False
    return identity(cycles(1))


def unselected_boolean_conditional_source_for_call() -> Morphism:
    _unused = False if False or True else source_for_bool()
    return identity(cycles(1))


def selected_nested_boolean_conditional_source_for_call() -> Morphism:
    _selected = (True if False or True else False) and source_for_bool()
    return identity(cycles(1))


def short_circuited_comparison_boolean_source_for_call() -> Morphism:
    _unused = (False == True == source_for_bool_only()) and source_for_bool_only()  # noqa: E712
    return identity(cycles(1))


def distinct_aggregate_identity_source_for_call() -> Morphism:
    left = [1]
    right = [1]
    _unused = (left is right) and source_for_bool()
    return identity(cycles(1))


def aliased_aggregate_identity_source_for_call() -> Morphism:
    shared = [1]
    alias = shared
    _selected = (shared is alias) and source_for_bool()
    return identity(cycles(1))


def source_without_native_specialization() -> Morphism:
    pass


def selected_source_without_native_specialization_call() -> Morphism:
    if True:
        return source_without_native_specialization()
    return identity(cycles(1))


def bound_probe_with_invalid_repeat(count: int = 1) -> Morphism:
    return repeat_morphism(identity(cycles(1)), count)


def comprehension_with_loop_free_bound_probe_failure() -> Morphism:
    _unused = [bound_probe_with_invalid_repeat(count) for count in (0,)]
    return identity(cycles(1))


def bound_probe_with_invalid_repeat_before_source_for(count: int = 1) -> Morphism:
    _unused = repeat_morphism(identity(cycles(1)), count)
    if count == 0:
        for _ in range(1):
            pass
    return identity(cycles(1))


def comprehension_with_bound_probe_failure_before_source_for() -> Morphism:
    _unused = [
        bound_probe_with_invalid_repeat_before_source_for(count) for count in (0,)
    ]
    return identity(cycles(1))


def bound_probe_with_invalid_range(step: int = 1) -> Morphism:
    _unused = range(0, 1, step)
    return identity(cycles(1))


def comprehension_with_loop_free_invalid_range_probe() -> Morphism:
    _unused = [bound_probe_with_invalid_range(step) for step in (0,)]
    return identity(cycles(1))


def bound_probe_with_invalid_range_before_source_for(step: int = 1) -> Morphism:
    _unused = range(0, 1, step)
    if step == 0:
        for _ in range(1):
            pass
    return identity(cycles(1))


def comprehension_with_invalid_range_probe_before_source_for() -> Morphism:
    _unused = [
        bound_probe_with_invalid_range_before_source_for(step) for step in (0,)
    ]
    return identity(cycles(1))


def bound_probe_with_invalid_filter_before_source_for(divisor: int = 1) -> Morphism:
    _unused = [item for item in (1,) if (item // divisor) > 0]
    if divisor == 0:
        for _ in range(1):
            pass
    return identity(cycles(1))


def comprehension_with_invalid_filter_probe_before_source_for() -> Morphism:
    _unused = [
        bound_probe_with_invalid_filter_before_source_for(divisor)
        for divisor in (0,)
    ]
    return identity(cycles(1))


class SourceForModule:
    def broken(self) -> Morphism:
        result = identity(0)
        for _ in range(3):
            result = result >> identity(cycles(4))
        return result


source_for_module = SourceForModule()
static_selected = True
static_unselected = False


class SourceForService:
    @property
    def modules(self) -> list[SourceForModule]:
        return [source_for_module]

    @property
    def selected_flags(self) -> list[bool]:
        return [static_selected]

    @property
    def unselected_flags(self) -> list[bool]:
        return [static_unselected]

    @property
    def empty_flags(self) -> list[bool]:
        return []

    def compile(self) -> Morphism:
        _selected = [module.broken() for module in self.modules]
        return identity(cycles(1))

    def compile_filtered(self) -> Morphism:
        _unused = [module.broken() for module in self.modules if False]
        return identity(cycles(1))

    def compile_wrapped(self) -> Morphism:
        _selected = [
            module.broken() if True else identity(cycles(1))
            for module in self.modules
        ]
        return identity(cycles(1))

    def compile_target_filtered(self) -> Morphism:
        selected = False  # noqa: F841 - exercises stale outer HIR binding
        _selected = [
            source_for_helper() for selected in self.selected_flags if selected
        ]
        return identity(cycles(1))

    def compile_target_filtered_out(self) -> Morphism:
        selected = True  # noqa: F841 - exercises stale outer HIR binding
        _unused = [
            source_for_helper() for selected in self.unselected_flags if selected
        ]
        return identity(cycles(1))

    def compile_object_target_filtered(self) -> Morphism:
        module = False  # noqa: F841 - target object must replace this stale binding
        _selected = [
            source_for_helper() for module in self.modules if module
        ]
        return identity(cycles(1))

    def compile_empty_static_property(self) -> Morphism:
        _unused = [source_for_helper() for selected in self.empty_flags if selected]
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


def test_selected_suite_rebinding_selects_a_later_source_for(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(compiler, selected_rebound_nested_if_source_for)


def test_named_expression_rebinding_updates_a_later_call_result(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(compiler, selected_named_expression_call_result_source_for)


def test_named_expression_rebinding_can_clear_a_later_call_result(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(unselected_named_expression_call_result_source_for)

    assert compiled.logical_duration_cycles == 1


def test_augmented_rebinding_selects_a_later_source_for(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(compiler, selected_augmented_rebound_source_for)


def test_named_expression_rebinding_selects_a_later_source_for(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(compiler, selected_named_expression_rebound_source_for)


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


def test_guard_does_not_add_boolean_lowering(compiler: Compiler) -> None:
    compiled = compiler.compile(loop_free_boolean_conditional_value)

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


def test_comprehension_preserves_outer_named_expression_rebindings(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_comprehension_named_expression_rebound_source_for,
    )


def test_comprehension_iteration_target_does_not_leak(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(comprehension_target_does_not_rebind_outer_guard)

    assert compiled.logical_duration_cycles == 1


def test_multi_generator_comprehension_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_multi_generator_comprehension_source_for_call,
        source_with_for=source_for_helper,
    )


def test_dictionary_comprehension_value_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_dictionary_comprehension_source_for_call,
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


def test_bound_comprehension_arguments_select_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_bound_argument_comprehension_source_for_call,
        source_with_for=source_for_helper,
    )


def test_bound_comprehension_arguments_can_leave_source_for_unselected(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(unselected_bound_argument_comprehension_source_for_call)

    assert compiled.logical_duration_cycles == 1


def test_boolean_conditional_argument_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_boolean_conditional_argument_source_for_call,
        source_with_for=source_for_helper,
    )


def test_boolean_conditional_argument_skips_unselected_source_for_calls(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(unselected_boolean_conditional_argument_source_for_call)

    assert compiled.logical_duration_cycles == 1


def test_bound_comprehension_arguments_preserve_positional_slots(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        comprehension_with_unavailable_positional_before_bound_guard,
        source_with_for=source_for_helper,
    )


def test_bound_guard_probe_does_not_surface_unrelated_lowering_errors(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(comprehension_with_loop_free_bound_probe_failure)

    assert compiled.logical_duration_cycles == 1


def test_bound_guard_probe_still_reports_a_later_selected_source_for(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        comprehension_with_bound_probe_failure_before_source_for,
        source_with_for=bound_probe_with_invalid_repeat_before_source_for,
    )


def test_bound_guard_probe_does_not_surface_an_invalid_range_error(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(comprehension_with_loop_free_invalid_range_probe)

    assert compiled.logical_duration_cycles == 1


def test_invalid_range_probe_still_reports_a_later_selected_source_for(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        comprehension_with_invalid_range_probe_before_source_for,
        source_with_for=bound_probe_with_invalid_range_before_source_for,
    )


def test_invalid_filter_probe_still_reports_a_later_selected_source_for(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        comprehension_with_invalid_filter_probe_before_source_for,
        source_with_for=bound_probe_with_invalid_filter_before_source_for,
    )


def test_static_property_comprehension_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        source_for_service.compile,
        source_with_for=SourceForModule.broken,
    )


def test_static_property_comprehension_filters_source_for_calls(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(source_for_service.compile_filtered)

    assert compiled.logical_duration_cycles == 1


def test_wrapped_static_property_comprehension_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        source_for_service.compile_wrapped,
        source_with_for=SourceForModule.broken,
    )


def test_static_property_filter_uses_its_target_value(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        source_for_service.compile_target_filtered,
        source_with_for=source_for_helper,
    )


def test_static_property_filter_does_not_use_a_stale_outer_value(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(source_for_service.compile_target_filtered_out)

    assert compiled.logical_duration_cycles == 1


def test_object_static_property_filter_uses_its_target_value(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        source_for_service.compile_object_target_filtered,
        source_with_for=source_for_helper,
    )


def test_empty_static_property_does_not_select_source_for_calls(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(source_for_service.compile_empty_static_property)

    assert compiled.logical_duration_cycles == 1


def test_consumed_reduce_lambda_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_reduce_lambda_source_for_call,
        source_with_for=source_for_helper,
    )


def test_consumed_reduce_lambda_alias_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_reduce_lambda_alias_source_for_call,
        source_with_for=source_for_helper,
    )


def test_consumed_named_reduce_callback_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_named_reduce_source_for_call,
        source_with_for=source_for_helper,
    )


def test_named_reduce_preserves_callback_return_value_between_invocations(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_return_left_reduce_source_for_call,
        source_with_for=return_left_source_for_reducer,
    )


def test_named_reduce_return_value_does_not_select_a_wrong_later_invocation(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(unselected_return_left_reduce_source_for_call)

    assert compiled.logical_duration_cycles == 1


def test_conditional_named_reduce_callback_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_conditional_named_reduce_source_for_call,
        source_with_for=direct_source_for_named_reducer,
    )


def test_conditional_named_reduce_skips_the_unselected_callback(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(unselected_conditional_named_reduce_source_for_call)

    assert compiled.logical_duration_cycles == 2


def test_consumed_conditional_reduce_lambda_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_conditional_reduce_lambda_source_for_call,
        source_with_for=source_for_helper,
    )


def test_consumed_reduce_binds_lambda_parameters_for_selected_paths(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_bound_reduce_parameter_source_for_call,
        source_with_for=source_for_helper,
    )


def test_initialized_single_item_reduce_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        initialized_single_item_reduce_lambda_source_for_call,
        source_with_for=source_for_helper,
    )


def test_single_item_reduce_skips_an_unconsumed_lambda_source_for_call(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(uninitialized_single_item_reduce_lambda_source_for_call)

    assert compiled.logical_duration_cycles == 1


def test_empty_initialized_reduce_does_not_select_its_lambda_source_for_call(
    compiler: Compiler,
) -> None:
    with pytest.raises(CatSeqCompileError) as error:
        compiler.compile(initialized_empty_reduce_lambda_source_for_call)

    assert "cannot reduce an empty Morphism aggregate" in str(error.value)
    assert SOURCE_FOR_GUARD_MESSAGE not in str(error.value)


@pytest.mark.parametrize(
    "entry",
    [
        short_circuited_and_source_for_call,
        short_circuited_or_source_for_call,
        short_circuited_zero_and_source_for_call,
        short_circuited_one_or_source_for_call,
        nested_short_circuited_and_source_for_call,
        nested_short_circuited_or_source_for_call,
    ],
)
def test_short_circuited_operands_do_not_select_source_for_calls(
    compiler: Compiler,
    entry: Callable[..., object],
) -> None:
    compiled = compiler.compile(entry)

    assert compiled.logical_duration_cycles == 1


@pytest.mark.parametrize("entry", [selected_and_source_for_call, selected_or_source_for_call])
def test_consumed_boolean_operands_select_source_for_calls(
    compiler: Compiler,
    entry: Callable[..., object],
) -> None:
    _assert_source_for_rejected(
        compiler,
        entry,
        source_with_for=source_for_bool,
    )


def test_short_circuited_comparison_operand_does_not_select_source_for_calls(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(short_circuited_comparison_source_for_call)

    assert compiled.logical_duration_cycles == 1


def test_consumed_comparison_operand_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_comparison_source_for_call,
        source_with_for=source_for_bool,
    )


def test_boolean_conditional_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_boolean_conditional_source_for_call,
        source_with_for=source_for_bool,
    )


def test_boolean_conditional_skips_unselected_source_for_calls(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(unselected_boolean_conditional_source_for_call)

    assert compiled.logical_duration_cycles == 1


def test_nested_boolean_conditional_selects_source_for_calls(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        selected_nested_boolean_conditional_source_for_call,
        source_with_for=source_for_bool,
    )


def test_comparison_result_short_circuits_an_outer_boolean_operation(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(short_circuited_comparison_boolean_source_for_call)

    assert compiled.logical_duration_cycles == 1


def test_distinct_equal_aggregates_are_not_identical_for_path_selection(
    compiler: Compiler,
) -> None:
    compiled = compiler.compile(distinct_aggregate_identity_source_for_call)

    assert compiled.logical_duration_cycles == 1


def test_aggregate_aliases_remain_identical_for_path_selection(
    compiler: Compiler,
) -> None:
    _assert_source_for_rejected(
        compiler,
        aliased_aggregate_identity_source_for_call,
        source_with_for=source_for_bool,
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
