import pytest

from catseq.types.common import Board, Channel, ChannelType
from catseq.types.rwg import RWGReady, RWGActive
from catseq.types.ttl import TTLState
from catseq.atomic import oasm_black_box, ttl_on
from catseq.compilation import compile_to_oasm_calls
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
    """Tests that operations outside the black box window do not cause an error."""
    start_state = RWGReady(carrier_freq=100)
    end_state = RWGActive(carrier_freq=100, rf_on=False, snapshot=(), pending_waveforms=())

    # A black box from t=0 to t=1000 cycles
    black_box = oasm_black_box(
        channel_states={ch0_rwg: (start_state, end_state)},
        duration_cycles=1000,
        board_funcs={board_rwg0: mock_user_func_A}
    )

    # A TTL pulse starting exactly when the black box ends
    ttl_pulse = identity(1000/250e6) >> ttl_on(ch2_ttl, start_state=TTLState.OFF)

    # This should compile without errors
    morphism = black_box | ttl_pulse
    try:
        compile_to_oasm_calls(morphism)
    except ValueError:
        pytest.fail("Compiler incorrectly flagged a non-conflicting operation.")
