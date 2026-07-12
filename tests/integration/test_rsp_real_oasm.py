"""Regression tests for RSP timing with the real OASM assembler."""

from oasm.dev.rsp import C_RSP
from oasm.rtmq2 import assembler, nop

from catseq import hold, us
from catseq.atomic import oasm_black_box
from catseq.compilation import timing_analysis
from catseq.compilation.compiler import compile_to_oasm_calls
from catseq.compilation.types import OASMAddress
from catseq.control import repeat_morphism
from catseq.hardware import rsp
from catseq.morphism import identity
from catseq.types import Board, Channel, ChannelType
from catseq.types.common import OperationType
from catseq.types.rsp import RSPPIDConfig, RSPReady, RSPWaveformParams


def _rsp_assembler():
    return assembler(None, [("rsp6", C_RSP)])


def _rsp_channel():
    return Channel(Board("RSP6"), 0, ChannelType.RSP)


def test_real_rsp_analysis_replaces_static_fallback_costs():
    channel = _rsp_channel()
    waveform = RSPWaveformParams(rf_out=0, amp=0.6)
    pid = RSPPIDConfig(
        adc_in=0,
        rf_out=0,
        dgt_source=0,
        setpoint=0.25,
    )
    morphism = (
        rsp.rf_config(waveform)
        >> hold(1 * us)
        >> rsp.pid_config(config=pid)
    )(channel, RSPReady(carrier_freq=80.0))

    events = compile_to_oasm_calls(
        morphism,
        _rsp_assembler(),
        _return_internal_events=True,
    )[OASMAddress.RSP6]

    measured_costs = {
        event.operation.operation_type: event.cost_cycles
        for event in events
        if event.operation.operation_type
        in (OperationType.RSP_RF_CONFIG, OperationType.RSP_PID_CONFIG)
    }
    assert measured_costs == {
        OperationType.RSP_RF_CONFIG: 13,
        OperationType.RSP_PID_CONFIG: 39,
    }


def test_real_rsp_analysis_uses_the_rsp_disassembler_core(monkeypatch):
    original_disassembler = timing_analysis.disassembler
    observed_cores = []

    def recording_disassembler(*, core):
        observed_cores.append(core)
        return original_disassembler(core=core)

    monkeypatch.setattr(timing_analysis, "disassembler", recording_disassembler)
    channel = _rsp_channel()
    waveform = RSPWaveformParams(rf_out=0, amp=0.6)

    compile_to_oasm_calls(
        rsp.rf_config(waveform)(
            channel,
            RSPReady(carrier_freq=80.0),
        ),
        _rsp_assembler(),
    )

    assert observed_cores == [C_RSP]


def test_rsp_repeat_uses_real_analyzed_body_duration():
    channel = _rsp_channel()
    waveform = RSPWaveformParams(rf_out=0, amp=0.6)
    body = rsp.rf_config(waveform)(
        channel,
        RSPReady(carrier_freq=80.0),
    ) >> identity(10 * us)

    repeated = repeat_morphism(body, 3, _rsp_assembler())

    assert repeated.total_duration_cycles == 15 + 3 * (24 + 2500)


def test_real_analysis_preserves_opaque_declared_duration():
    channel = _rsp_channel()
    state = RSPReady(carrier_freq=80.0)

    def opaque_body():
        nop()

    morphism = oasm_black_box(
        channel_states={channel: (state, state)},
        duration_cycles=1000,
        board_funcs={channel.board: opaque_body},
    )

    events = compile_to_oasm_calls(
        morphism,
        _rsp_assembler(),
        _return_internal_events=True,
    )[OASMAddress.RSP6]
    opaque_event = next(
        event
        for event in events
        if event.operation.operation_type is OperationType.OPAQUE_OASM_FUNC
    )

    assert opaque_event.cost_cycles == 1000
