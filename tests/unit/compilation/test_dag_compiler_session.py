import pytest

from catseq.compilation.compiler import compile_to_oasm_calls
from catseq.compilation.dag import CompilerSession
from catseq.compilation.types import OASMAddress, OASMFunction
from catseq.expr import var
from catseq.morphism.arena import ProgramArena
from catseq.time_utils import mu
from catseq.types.common import (
    AtomicMorphism,
    Board,
    Channel,
    ChannelType,
    OperationType,
)
from catseq.types.ttl import TTLState


BOARD = Board("rwg0")
BOARD1 = Board("rwg1")
CH0 = Channel(BOARD, 0, ChannelType.TTL)
CH1 = Channel(BOARD, 1, ChannelType.TTL)
CH2 = Channel(BOARD1, 0, ChannelType.TTL)


def _ttl_on(channel: Channel) -> AtomicMorphism:
    return AtomicMorphism(
        channel=channel,
        start_state=TTLState.OFF,
        end_state=TTLState.ON,
        duration_cycles=0,
        operation_type=OperationType.TTL_ON,
    )


def _ttl_off(channel: Channel) -> AtomicMorphism:
    return AtomicMorphism(
        channel=channel,
        start_state=TTLState.ON,
        end_state=TTLState.OFF,
        duration_cycles=0,
        operation_type=OperationType.TTL_OFF,
    )


def test_compiler_session_compiles_serial_ttl_dag_without_lanes():
    arena = ProgramArena()
    root = arena.serial(
        arena.serial(arena.atomic(_ttl_on(CH0)), arena.wait(2500 * mu)),
        arena.atomic(_ttl_off(CH0)),
    )

    result = CompilerSession(arena.freeze(root)).bind({})

    assert [
        (call.dsl_func, call.args)
        for call in result.calls_by_board[OASMAddress.RWG0]
    ] == [
        (OASMFunction.TTL_SET, (1, 1, "rwg")),
        (OASMFunction.WAIT, (2500,)),
        (OASMFunction.TTL_SET, (1, 0, "rwg")),
    ]


def test_compiler_session_merges_parallel_ttl_cohorts():
    arena = ProgramArena()
    left = arena.serial(
        arena.serial(arena.atomic(_ttl_on(CH0)), arena.wait(2500 * mu)),
        arena.atomic(_ttl_off(CH0)),
    )
    right = arena.serial(
        arena.serial(
            arena.serial(arena.atomic(_ttl_on(CH1)), arena.wait(1250 * mu)),
            arena.atomic(_ttl_off(CH1)),
        ),
        arena.wait(1250 * mu),
    )

    result = CompilerSession(arena.freeze(arena.parallel(left, right))).bind({})

    assert [
        (call.dsl_func, call.args)
        for call in result.calls_by_board[OASMAddress.RWG0]
    ] == [
        (OASMFunction.TTL_SET, (3, 3, "rwg")),
        (OASMFunction.WAIT, (1250,)),
        (OASMFunction.TTL_SET, (2, 0, "rwg")),
        (OASMFunction.WAIT, (1250,)),
        (OASMFunction.TTL_SET, (1, 0, "rwg")),
    ]


def test_compiler_session_invalidates_only_parameter_dependents():
    arena = ProgramArena()
    on = arena.atomic(_ttl_on(CH0))
    delay = arena.wait(var("wait_time"))
    before_off = arena.serial(on, delay)
    off = arena.atomic(_ttl_off(CH0))
    root = arena.serial(before_off, off)
    session = CompilerSession(arena.freeze(root))
    session.bind({"wait_time": 100 * mu})

    updated = session.bind({"wait_time": 200 * mu})

    assert updated.delta.dirty_nodes == frozenset({delay, before_off, root})
    assert [
        (call.dsl_func, call.args)
        for call in updated.calls_by_board[OASMAddress.RWG0]
    ] == [
        (OASMFunction.TTL_SET, (1, 1, "rwg")),
        (OASMFunction.WAIT, (200,)),
        (OASMFunction.TTL_SET, (1, 0, "rwg")),
    ]


def test_compile_to_oasm_calls_dispatches_arena_program():
    arena = ProgramArena()
    root = arena.serial(
        arena.serial(arena.atomic(_ttl_on(CH0)), arena.wait(var("delay"))),
        arena.atomic(_ttl_off(CH0)),
    )

    calls_by_board = compile_to_oasm_calls(
        arena.freeze(root),
        bindings={"delay": 75 * mu},
    )

    assert [
        (call.dsl_func, call.args)
        for call in calls_by_board[OASMAddress.RWG0]
    ] == [
        (OASMFunction.TTL_SET, (1, 1, "rwg")),
        (OASMFunction.WAIT, (75,)),
        (OASMFunction.TTL_SET, (1, 0, "rwg")),
    ]


def test_parameter_update_recompiles_only_changed_board():
    arena = ProgramArena()
    variable_board = arena.serial(
        arena.serial(arena.atomic(_ttl_on(CH0)), arena.wait(var("delay"))),
        arena.atomic(_ttl_off(CH0)),
    )
    fixed_board = arena.serial(
        arena.serial(arena.atomic(_ttl_on(CH2)), arena.wait(300 * mu)),
        arena.atomic(_ttl_off(CH2)),
    )
    session = CompilerSession(
        arena.freeze(arena.parallel(variable_board, fixed_board))
    )
    session.bind({"delay": 100 * mu})

    updated = session.bind({"delay": 200 * mu})

    assert updated.delta.recompiled_boards == frozenset({OASMAddress.RWG0})
    assert updated.delta.changed_boards == frozenset({OASMAddress.RWG0})


def test_failed_binding_does_not_replace_last_successful_result():
    arena = ProgramArena()
    root = arena.serial(
        arena.serial(arena.atomic(_ttl_on(CH0)), arena.wait(var("delay"))),
        arena.atomic(_ttl_off(CH0)),
    )
    session = CompilerSession(arena.freeze(root))
    initial = session.bind({"delay": 100 * mu})

    with pytest.raises(ValueError, match="non-negative"):
        session.bind({"delay": -1 * mu})
    recovered = session.bind({})

    assert recovered.calls_by_board == initial.calls_by_board
    assert recovered.delta.dirty_nodes == frozenset()


def test_strict_state_error_reports_arena_node():
    arena = ProgramArena()
    left = arena.atomic(_ttl_on(CH0))
    right = arena.atomic(_ttl_on(CH0))
    root = arena.serial(left, right, strict=True)

    with pytest.raises(ValueError, match=f"arena node {root}"):
        CompilerSession(arena.freeze(root)).bind({})


def test_unreachable_parameterized_nodes_are_not_bound_or_compiled():
    arena = ProgramArena()
    arena.wait(var("unused"))
    root = arena.atomic(_ttl_on(CH0))

    result = CompilerSession(arena.freeze(root)).bind({})

    assert result.delta.dirty_nodes == frozenset({root})


def test_identity_only_atomic_preserves_board_horizon():
    identity = AtomicMorphism(
        channel=CH0,
        start_state=TTLState.OFF,
        end_state=TTLState.OFF,
        duration_cycles=100,
        operation_type=OperationType.IDENTITY,
    )
    arena = ProgramArena()
    root = arena.atomic(identity)

    result = CompilerSession(arena.freeze(root)).bind({})

    assert [
        (call.dsl_func, call.args)
        for call in result.calls_by_board[OASMAddress.RWG0]
    ] == [(OASMFunction.WAIT, (100,))]


def test_board_resolution_error_reports_source_arena_node():
    bad_channel = Channel(Board("unknown"), 0, ChannelType.TTL)
    arena = ProgramArena()
    root = arena.atomic(_ttl_on(bad_channel))

    with pytest.raises(ValueError, match=f"arena node {root}"):
        CompilerSession(arena.freeze(root)).bind({})
