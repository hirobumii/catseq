import pytest

from catseq import us
from catseq.atomic import ttl_on
from catseq.compilation.compiler import compile_to_oasm_calls
from catseq.expr import Expr, input_state, realize_morphism, resolve_value, var
from catseq.hardware import hold, rwg
from catseq.morphism import identity
from catseq.types.common import Board, Channel, ChannelType, OperationType, TimingKind
from catseq.types.rwg import RWGActive, StaticWaveform
from catseq.types.ttl import TTLState


RWG0 = Board("RWG0")
TTL_CH0 = Channel(RWG0, 0, ChannelType.TTL)
RWG_CH0 = Channel(RWG0, 0, ChannelType.RWG)


def test_expr_rejects_python_bool():
    expr = var("x") + 1
    with pytest.raises(TypeError):
        bool(expr)


def test_expr_resolves_composed_arithmetic_tree():
    expr = (var("x") + 1) * 2
    assert resolve_value(expr, None, {"x": 3}) == 8


def test_expr_resolves_two_runtime_operands():
    expr = var("x") * var("y")
    assert resolve_value(expr, None, {"x": 6, "y": 7}) == 42


def test_expr_resolves_nested_two_operand_tree():
    expr = (var("x") + 1) * (var("y") - 2)
    assert resolve_value(expr, None, {"x": 4, "y": 9}) == 35


def test_expr_resolve_nested_dataclass():
    waveform = StaticWaveform(freq=var("f"), amp=0.5, sbg_id=0, phase=0.0)
    resolved = resolve_value(waveform, None, {"f": 10.0})
    assert isinstance(resolved, StaticWaveform)
    assert resolved.freq == 10.0
    assert resolved.amp == 0.5


def test_expr_resolve_nested_containers():
    value = {
        "a": (var("x") + 1, var("y") * 2),
        "b": [var("x") * var("y"), 5],
    }
    resolved = resolve_value(value, None, {"x": 3, "y": 4})
    assert resolved == {
        "a": (4, 8),
        "b": [12, 5],
    }


def test_symbolic_identity_duration_survives_in_source_morphism():
    wait_expr = var("t") * us
    morphism = ttl_on(TTL_CH0) >> identity(wait_expr)
    assert isinstance(morphism.total_duration_expr, Expr)
    assert morphism.lanes[TTL_CH0].operations[0].duration_cycles == 0
    assert morphism.lanes[TTL_CH0].operations[1].timing_kind == TimingKind.DELAY


def test_realize_morphism_resolves_symbolic_duration():
    wait_expr = var("t") * us
    morphism = ttl_on(TTL_CH0) >> hold(wait_expr)(TTL_CH0, TTLState.ON)
    realized = realize_morphism(morphism, {"t": 10})
    assert realized.total_duration_cycles == 2500


def test_realize_morphism_resolves_composed_rwg_expr_values():
    start_state = RWGActive(
        carrier_freq=1000.0,
        rf_on=False,
        snapshot=(StaticWaveform(sbg_id=0, freq=10.0, amp=0.5, phase=0.0),),
    )
    morphism = rwg.linear_ramp(
        [StaticWaveform(freq=(var("f") + 1) * 2, amp=var("a1") * var("a2"), sbg_id=0, phase=0.0)],
        (var("dur") + 1) * us,
    )(RWG_CH0, start_state)
    realized = realize_morphism(morphism, {"f": 4.0, "a1": 0.2, "a2": 3.0, "dur": 9})
    assert realized.total_duration_cycles == 2500
    load_events = [op for op in realized.lanes[RWG_CH0].operations if op.operation_type == OperationType.RWG_LOAD_COEFFS]
    assert len(load_events) >= 1
    first_params = load_events[0].end_state.pending_waveforms[0]
    assert first_params.freq_coeffs[0] == 10.0
    assert first_params.amp_coeffs[0] == 0.5


def test_compile_time_float_exprs_are_allowed_in_rwg_values():
    start_state = RWGActive(
        carrier_freq=1000.0,
        rf_on=False,
        snapshot=(StaticWaveform(sbg_id=0, freq=10.0, amp=0.5, phase=0.0),),
    )
    morphism = rwg.linear_ramp(
        [
            StaticWaveform(
                freq=var("freq_base") + 0.25,
                amp=(var("amp_scale") * 0.2) + 0.1,
                sbg_id=0,
                phase=0.0,
            )
        ],
        10 * us,
    )(RWG_CH0, start_state)
    realized = realize_morphism(
        morphism,
        {
            "freq_base": 12.5,
            "amp_scale": 1.5,
        },
    )
    load_events = [
        op
        for op in realized.lanes[RWG_CH0].operations
        if op.operation_type == OperationType.RWG_LOAD_COEFFS
    ]
    assert len(load_events) >= 2

    ramp_params = load_events[0].end_state.pending_waveforms[0]
    static_params = load_events[1].end_state.pending_waveforms[0]

    # Start of ramp remains the current waveform values.
    assert isinstance(ramp_params.freq_coeffs[0], float)
    assert isinstance(ramp_params.amp_coeffs[0], float)
    assert ramp_params.freq_coeffs[0] == 10.0
    assert ramp_params.amp_coeffs[0] == 0.5

    # Slope terms should be realized from float exprs:
    # target_freq = 12.5 + 0.25 = 12.75 => (12.75 - 10.0) / 10us = 0.275 MHz/us
    # target_amp = 1.5 * 0.2 + 0.1 = 0.4 => (0.4 - 0.5) / 10us = -0.01 /us
    assert isinstance(ramp_params.freq_coeffs[1], float)
    assert isinstance(ramp_params.amp_coeffs[1], float)
    assert ramp_params.freq_coeffs[1] == pytest.approx(0.275)
    assert ramp_params.amp_coeffs[1] == pytest.approx(-0.01)

    # The terminal static load should also contain the realized float target values.
    assert static_params.freq_coeffs[0] == pytest.approx(12.75)
    assert static_params.amp_coeffs[0] == pytest.approx(0.4)
    assert static_params.freq_coeffs[1] == 0.0
    assert static_params.amp_coeffs[1] == 0.0


def test_compile_time_float_exprs_are_allowed_in_rwg_initialize():
    morphism = rwg.initialize(carrier_freq=var("carrier") + 0.125)(
        RWG_CH0,
        start_state=rwg.RWGUninitialized(),
    )
    realized = realize_morphism(morphism, {"carrier": 99.875})
    final_state = realized.lanes[RWG_CH0].operations[-1].end_state
    assert isinstance(final_state.carrier_freq, float)
    assert final_state.carrier_freq == 100.0


def test_compile_rejects_unresolved_expr():
    morphism = ttl_on(TTL_CH0) >> identity(var("t") * us)
    with pytest.raises(TypeError, match="fully concrete morphism"):
        compile_to_oasm_calls(morphism)


def test_rwg_initialize_and_set_state_accept_expr_values():
    state = rwg.initialize(carrier_freq=var("carrier"))(
        RWG_CH0,
        start_state=rwg.RWGUninitialized(),
    )
    assert isinstance(state.lanes[RWG_CH0].operations[-1].end_state.carrier_freq, Expr)

    start_state = RWGActive(
        carrier_freq=1000.0,
        rf_on=False,
        snapshot=(StaticWaveform(sbg_id=0, freq=10.0, amp=0.5, phase=0.0),),
    )
    morphism = rwg.linear_ramp(
        [StaticWaveform(freq=var("freq"), amp=0.8, sbg_id=0, phase=0.0)],
        var("dur") * us,
    )(RWG_CH0, start_state)
    assert isinstance(morphism.total_duration_expr, Expr)
