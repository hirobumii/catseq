import pytest

from catseq.types.common import Board, Channel, ChannelType, OperationType
from catseq.types.rwg import RWGReady, RWGActive
from catseq.types.ttl import TTLState
from catseq.atomic import oasm_black_box, ttl_off, ttl_on
from catseq.compilation import compile_to_oasm_calls
from catseq.compilation.pipeline import extract_and_translate
from catseq.compilation.types import OASMAddress, OASMFunction
from catseq.morphism import identity

# Mock hardware setup
board_rwg0 = Board("RWG0")
ch0_rwg = Channel(board_rwg0, 0, ChannelType.RWG)
ch1_rwg = Channel(board_rwg0, 1, ChannelType.RWG)
ch2_ttl = Channel(board_rwg0, 2, ChannelType.TTL)

# Mock user-defined OASM functions
def mock_user_func_A(arg1, kwarg1=None):
    """Mock function for testing."""
    pass

def mock_user_func_B():
    """Another mock function for testing."""
    pass


def test_single_channel_black_box():
    """Tests compilation of a simple, single-channel black box."""
    start_state = RWGReady(carrier_freq=100)
    end_state = RWGActive(carrier_freq=100, rf_on=True, snapshot=(), pending_waveforms=())

    black_box = oasm_black_box(
        channel_states={ch0_rwg: (start_state, end_state)},
        duration_cycles=1000,
        board_funcs={board_rwg0: mock_user_func_A},
        user_args=("hello",),
        user_kwargs={'kwarg1': 'world'}
    )

    compiled_calls = compile_to_oasm_calls(black_box)
    
    assert OASMAddress.RWG0 in compiled_calls
    rwg0_calls = compiled_calls[OASMAddress.RWG0]
    
    user_func_calls = [c for c in rwg0_calls if c.dsl_func == OASMFunction.USER_DEFINED_FUNC]
    assert len(user_func_calls) == 1
    
    call_payload = user_func_calls[0].args
    assert call_payload[0] == mock_user_func_A
    assert call_payload[1] == ("hello",)
    assert call_payload[2] == {'kwarg1': 'world'}


def test_multi_channel_black_box_merge():
    """Tests that a multi-channel black box on the same board generates only one call."""
    start_state = RWGReady(carrier_freq=100)
    end_state = RWGActive(carrier_freq=100, rf_on=False, snapshot=(), pending_waveforms=())

    black_box = oasm_black_box(
        channel_states={
            ch0_rwg: (start_state, end_state),
            ch1_rwg: (start_state, end_state),
        },
        duration_cycles=500,
        board_funcs={board_rwg0: mock_user_func_B}
    )

    compiled_calls = compile_to_oasm_calls(black_box)
    assert OASMAddress.RWG0 in compiled_calls
    rwg0_calls = compiled_calls[OASMAddress.RWG0]

    user_func_calls = [c for c in rwg0_calls if c.dsl_func == OASMFunction.USER_DEFINED_FUNC]
    assert len(user_func_calls) == 1
    assert user_func_calls[0].args[0] == mock_user_func_B


def test_multi_channel_black_box_extracts_single_board_scoped_event():
    start_state = RWGReady(carrier_freq=100)
    end_state = RWGActive(carrier_freq=100, rf_on=False, snapshot=(), pending_waveforms=())

    black_box = oasm_black_box(
        channel_states={
            ch0_rwg: (start_state, end_state),
            ch1_rwg: (start_state, end_state),
        },
        duration_cycles=500,
        board_funcs={board_rwg0: mock_user_func_B},
    )

    events_by_board = extract_and_translate(black_box)
    rwg0_events = events_by_board[OASMAddress.RWG0]
    opaque_events = [e for e in rwg0_events if e.operation.operation_type == OperationType.OPAQUE_OASM_FUNC]

    assert len(opaque_events) == 1
    opaque = opaque_events[0]
    assert opaque.operation.channel is None
    assert opaque.blackbox_board == OASMAddress.RWG0.value
    assert len([c for c in opaque.oasm_calls if c.dsl_func == OASMFunction.USER_DEFINED_FUNC]) == 1


def test_multi_channel_black_box_is_order_independent():
    start_state = RWGReady(carrier_freq=100)
    end_state = RWGActive(carrier_freq=100, rf_on=False, snapshot=(), pending_waveforms=())

    black_box_a = oasm_black_box(
        channel_states={
            ch0_rwg: (start_state, end_state),
            ch1_rwg: (start_state, end_state),
        },
        duration_cycles=500,
        board_funcs={board_rwg0: mock_user_func_B},
    )
    black_box_b = oasm_black_box(
        channel_states={
            ch1_rwg: (start_state, end_state),
            ch0_rwg: (start_state, end_state),
        },
        duration_cycles=500,
        board_funcs={board_rwg0: mock_user_func_B},
    )

    events_a = extract_and_translate(black_box_a)[OASMAddress.RWG0]
    events_b = extract_and_translate(black_box_b)[OASMAddress.RWG0]
    opaque_a = next(e for e in events_a if e.blackbox_group_id is not None)
    opaque_b = next(e for e in events_b if e.blackbox_group_id is not None)

    assert opaque_a.timestamp_cycles == opaque_b.timestamp_cycles
    assert opaque_a.operation.duration_cycles == opaque_b.operation.duration_cycles
    assert opaque_a.operation.channel is None
    assert opaque_b.operation.channel is None


def test_black_box_exclusivity_fail():
    """Tests that the compiler fails if another operation overlaps with a black box."""
    start_state = RWGReady(carrier_freq=100)
    end_state = RWGActive(carrier_freq=100, rf_on=False, snapshot=(), pending_waveforms=())

    # A black box from t=0 to t=1000
    black_box = oasm_black_box(
        channel_states={ch0_rwg: (start_state, end_state)},
        duration_cycles=1000,
        board_funcs={board_rwg0: mock_user_func_A}
    )

    # A TTL pulse at t=500 on the same board, which is inside the black box's window
    ttl_pulse = identity(500/250e6) >> ttl_on(ch2_ttl, start_state=TTLState.OFF)

    # Compose them in parallel - this should fail validation
    conflicting_morphism = black_box | ttl_pulse

    with pytest.raises(ValueError, match="conflicts with a black-box operation"):
        compile_to_oasm_calls(conflicting_morphism)


def test_black_box_no_conflict():
    """Tests that operations strictly after the black box window do not cause an error."""
    start_state = RWGReady(carrier_freq=100)
    end_state = RWGActive(carrier_freq=100, rf_on=False, snapshot=(), pending_waveforms=())

    # A black box from t=0 to t=1000 cycles
    black_box = oasm_black_box(
        channel_states={ch0_rwg: (start_state, end_state)},
        duration_cycles=1000,
        board_funcs={board_rwg0: mock_user_func_A}
    )

    # A TTL pulse starting strictly after the black box ends
    ttl_pulse = identity(1001/250e6) >> ttl_on(ch2_ttl, start_state=TTLState.OFF)

    # This should compile without errors
    morphism = black_box | ttl_pulse
    compile_to_oasm_calls(morphism)


def test_black_box_allows_instantaneous_ops_at_start_boundary():
    """Opaque timed regions should allow same-board point events at the left boundary."""
    start_state = RWGReady(carrier_freq=100)
    end_state = RWGActive(carrier_freq=100, rf_on=False, snapshot=(), pending_waveforms=())

    black_box = oasm_black_box(
        channel_states={ch0_rwg: (start_state, end_state)},
        duration_cycles=1000,
        board_funcs={board_rwg0: mock_user_func_A},
    )

    compile_to_oasm_calls(ttl_on(ch2_ttl, start_state=TTLState.OFF) | black_box)


def test_black_box_rejects_instantaneous_ops_at_end_boundary():
    """Opaque timed regions should still reject same-board point events at the right boundary."""
    start_state = RWGReady(carrier_freq=100)
    end_state = RWGActive(carrier_freq=100, rf_on=False, snapshot=(), pending_waveforms=())

    black_box = oasm_black_box(
        channel_states={ch0_rwg: (start_state, end_state)},
        duration_cycles=1000,
        board_funcs={board_rwg0: mock_user_func_A},
    )

    with pytest.raises(ValueError, match="conflicts with a black-box operation"):
        compile_to_oasm_calls(
            black_box | (identity(1000/250e6) >> ttl_on(ch2_ttl, start_state=TTLState.OFF))
        )


def test_multi_board_black_box_events_share_start_time_and_duration():
    board_rwg1 = Board("RWG1")
    ch_other = Channel(board_rwg1, 0, ChannelType.RWG)
    start_state = RWGReady(carrier_freq=100)
    end_state = RWGActive(carrier_freq=100, rf_on=False, snapshot=(), pending_waveforms=())

    black_box = oasm_black_box(
        channel_states={
            ch0_rwg: (start_state, end_state),
            ch_other: (start_state, end_state),
        },
        duration_cycles=500,
        board_funcs={board_rwg0: mock_user_func_A, board_rwg1: mock_user_func_A},
    )

    events_by_board = extract_and_translate(black_box)
    opaque0 = next(e for e in events_by_board[OASMAddress.RWG0] if e.blackbox_group_id is not None)
    opaque1 = next(e for e in events_by_board[OASMAddress.RWG1] if e.blackbox_group_id is not None)

    assert opaque0.timestamp_cycles == opaque1.timestamp_cycles
    assert opaque0.operation.duration_cycles == opaque1.operation.duration_cycles
    assert opaque0.blackbox_group_id == opaque1.blackbox_group_id
