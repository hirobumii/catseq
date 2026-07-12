import pytest

from catseq.compilation.compiler import compile_to_oasm_calls
from catseq.compilation.dag import CompilerSession
from catseq.compilation.types import OASMAddress, OASMFunction
from catseq.control import repeat_morphism
from catseq.atomic import ttl_off, ttl_on
from catseq.expr import var
from catseq.morphism import (
    MorphismDef,
    MorphismEndStateView,
    arena_build,
    deferred_batch_from_state_source,
    identity,
)
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


def test_unknown_board_preserves_legacy_rwg0_fallback():
    bad_channel = Channel(Board("unknown"), 0, ChannelType.TTL)
    arena = ProgramArena()
    root = arena.atomic(_ttl_on(bad_channel))

    result = CompilerSession(arena.freeze(root)).bind({})

    assert OASMAddress.RWG0 in result.calls_by_board


def test_existing_morphism_api_compiles_through_dag_with_bindings():
    morphism = (
        ttl_on(CH0, start_state=TTLState.OFF)
        >> identity(var("delay"))
        >> ttl_off(CH0, start_state=TTLState.ON)
    )

    calls = compile_to_oasm_calls(
        morphism,
        bindings={"delay": 75 * mu},
    )

    assert [
        (call.dsl_func, call.args)
        for call in calls[OASMAddress.RWG0]
    ] == [
        (OASMFunction.TTL_SET, (1, 1, "rwg")),
        (OASMFunction.WAIT, (75,)),
        (OASMFunction.TTL_SET, (1, 0, "rwg")),
    ]


def test_morphism_def_application_is_lazy_until_compilation():
    observed_states = []

    def turn_off(channel, start_state):
        observed_states.append(start_state)
        return identity(100 * mu) >> ttl_off(
            channel,
            start_state=start_state,
        )

    morphism = ttl_on(CH0, start_state=TTLState.OFF) >> MorphismDef(turn_off)

    assert observed_states == []

    calls = compile_to_oasm_calls(morphism)

    assert observed_states == [TTLState.ON]
    assert [
        (call.dsl_func, call.args)
        for call in calls[OASMAddress.RWG0]
    ] == [
        (OASMFunction.TTL_SET, (1, 1, "rwg")),
        (OASMFunction.WAIT, (100,)),
        (OASMFunction.TTL_SET, (1, 0, "rwg")),
    ]


def test_lazy_definitions_thread_state_across_structural_waits():
    observed_states = []

    def hold_state(_channel, start_state):
        observed_states.append(start_state)
        return identity(100 * mu)

    def turn_off(channel, start_state):
        observed_states.append(start_state)
        return ttl_off(channel, start_state=start_state)

    morphism = (
        ttl_on(CH0, start_state=TTLState.OFF)
        >> MorphismDef(hold_state)
        >> identity(25 * mu)
        >> MorphismDef(turn_off)
    )

    assert observed_states == []

    calls = compile_to_oasm_calls(morphism)

    assert observed_states == [TTLState.ON, TTLState.ON]
    assert [
        (call.dsl_func, call.args)
        for call in calls[OASMAddress.RWG0]
    ] == [
        (OASMFunction.TTL_SET, (1, 1, "rwg")),
        (OASMFunction.WAIT, (125,)),
        (OASMFunction.TTL_SET, (1, 0, "rwg")),
    ]


def test_parameter_rebind_reuses_lowered_definition():
    generator_calls = []
    delay = var("deferred_delay")

    def parameterized_hold(_channel, start_state):
        generator_calls.append(start_state)
        return identity(delay)

    morphism = ttl_on(CH0, start_state=TTLState.OFF) >> MorphismDef(
        parameterized_hold
    )
    session = CompilerSession(morphism.arena_program)

    session.bind({"deferred_delay": 100 * mu})
    updated = session.bind({"deferred_delay": 200 * mu})

    assert generator_calls == [TTLState.ON]
    assert updated.delta.recompiled_boards == frozenset({OASMAddress.RWG0})
    assert [
        (call.dsl_func, call.args)
        for call in updated.calls_by_board[OASMAddress.RWG0]
    ] == [
        (OASMFunction.TTL_SET, (1, 1, "rwg")),
        (OASMFunction.WAIT, (200,)),
    ]


def test_arena_builder_records_explicit_channel_definition_lazily():
    observed_states = []

    def turn_on(channel, start_state):
        observed_states.append(start_state)
        return ttl_on(channel, start_state=start_state)

    @arena_build
    def build():
        return MorphismDef(turn_on)(CH0, TTLState.OFF)

    morphism = build()

    assert observed_states == []

    compile_to_oasm_calls(morphism)

    assert observed_states == [TTLState.OFF]


def test_deferred_batch_reads_state_from_source_root_at_compilation():
    observed_states = []

    def turn_on(channel, start_state):
        observed_states.append(start_state)
        return ttl_on(channel, start_state=start_state)

    def turn_off(channel, start_state):
        observed_states.append(start_state)
        return identity(100 * mu) >> ttl_off(
            channel,
            start_state=start_state,
        )

    @arena_build
    def build():
        source = MorphismDef(turn_on)(CH0, TTLState.OFF)
        states = MorphismEndStateView(source)
        batch = deferred_batch_from_state_source(
            states.morphism,
            {CH0: MorphismDef(turn_off)},
        )
        return source >> batch

    morphism = build()

    assert observed_states == []

    calls = compile_to_oasm_calls(morphism)

    assert observed_states == [TTLState.OFF, TTLState.ON]
    assert [
        (call.dsl_func, call.args)
        for call in calls[OASMAddress.RWG0]
    ] == [
        (OASMFunction.TTL_SET, (1, 1, "rwg")),
        (OASMFunction.WAIT, (100,)),
        (OASMFunction.TTL_SET, (1, 0, "rwg")),
    ]


def test_symbolic_deferred_channels_align_after_binding():
    delay = var("channel_delay")
    morphism = (
        ttl_on(CH0, start_state=TTLState.OFF)
        | ttl_on(CH1, start_state=TTLState.OFF)
    ) >> {
        CH0: MorphismDef(lambda _channel, _state: identity(delay)),
        CH1: MorphismDef(lambda _channel, _state: identity(100 * mu)),
    }
    session = CompilerSession(morphism.arena_program)

    shorter = session.bind({"channel_delay": 50 * mu})
    longer = session.bind({"channel_delay": 200 * mu})

    assert [
        (call.dsl_func, call.args)
        for call in shorter.calls_by_board[OASMAddress.RWG0]
    ][-1] == (OASMFunction.WAIT, (100,))
    assert [
        (call.dsl_func, call.args)
        for call in longer.calls_by_board[OASMAddress.RWG0]
    ][-1] == (OASMFunction.WAIT, (200,))


def test_symbolic_hardware_repeat_specializes_at_bind_time():
    delay = var("repeat_delay")

    @arena_build
    def build():
        body = (
            ttl_on(CH0, start_state=TTLState.OFF)
            >> identity(delay)
            >> ttl_off(CH0, start_state=TTLState.ON)
        )
        return repeat_morphism(body, 3, None)

    session = CompilerSession(build().arena_program)

    first = session.bind({"repeat_delay": 100 * mu})
    updated = session.bind({"repeat_delay": 200 * mu})

    assert first.delta.revision == 1
    assert updated.delta.revision == 2
    assert updated.delta.recompiled_boards == frozenset({OASMAddress.RWG0})
    assert updated.calls_by_board[OASMAddress.RWG0]


def test_deferred_batch_error_reports_its_arena_node():
    source = ttl_on(CH0, start_state=TTLState.OFF)

    def invalid_transition(_channel, _state):
        raise TypeError("invalid transition")

    batch = deferred_batch_from_state_source(
        source,
        {CH0: MorphismDef(invalid_transition)},
    )

    with pytest.raises(TypeError, match="deferred batch arena node"):
        compile_to_oasm_calls(source >> batch)
