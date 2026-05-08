import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _install_fake_oasm_modules():
    def noop(*args, **kwargs):
        return None

    oasm = types.ModuleType("oasm")
    oasm.domain = lambda *args, **kwargs: (lambda func: func)
    rtmq2 = types.ModuleType("oasm.rtmq2")
    for name in ["sfs", "amk", "wait", "send_trig_code", "wait_rtlk_trig", "nop", "clo", "call", "label"]:
        setattr(rtmq2, name, noop)
    rtmq2.Func = lambda *args, **kwargs: types.SimpleNamespace(__enter__=lambda self: None, __exit__=lambda self, *exc: False)
    rtmq2.Return = noop
    rtmq2.R = []
    rtmq2.core_ctx = {}
    rtmq2.core_reg = []
    rtmq2.core_regq = []
    rtmq2.asm = types.SimpleNamespace(intf=object())
    rtmq2.H = object()
    rtmq2.P = object()
    rtmq2.disassembler = lambda core=None: (lambda asm: [])

    dev = types.ModuleType("oasm.dev")
    rwg = types.ModuleType("oasm.dev.rwg")
    rwg.fte = types.SimpleNamespace(cfg=noop)
    rwg.rwg = types.SimpleNamespace(
        rsm=types.SimpleNamespace(on=noop),
        pdm=types.SimpleNamespace(source=noop),
        cds=types.SimpleNamespace(mux=noop),
        rst_cic=noop,
        carrier=noop,
        frq=noop,
        amp=noop,
    )
    rwg.sbg = types.SimpleNamespace(ctrl=noop)
    rwg.C_RWG = object()

    rsp = types.ModuleType("oasm.dev.rsp")
    for name in [
        "dds_prof", "dds_carrier", "dds_signal", "rsp_signal", "mua_cph",
        "mua_cpl", "mua_gan", "mua_ofs", "acu_prh", "acu_prl",
        "mod_inp", "mix_cfg", "dgt_cfg", "clo", "cnv_cfg", "cnv_pid",
        "adc_ctrl",
    ]:
        setattr(rsp, name, noop)
    rsp.R = types.SimpleNamespace(
        dac_inp={}, ext_adc=object(), dgt_cfg={}, mix_ipa={}, cnv_inp={},
        acu_inp={}, mua_inp={}, rfg_inp={},
    )

    sys.modules.setdefault("oasm", oasm)
    sys.modules.setdefault("oasm.rtmq2", rtmq2)
    sys.modules.setdefault("oasm.dev", dev)
    sys.modules.setdefault("oasm.dev.rwg", rwg)
    sys.modules.setdefault("oasm.dev.rsp", rsp)


_install_fake_oasm_modules()

from catseq import hold, us  # noqa: E402
from catseq.atomic import (  # noqa: E402
    rsp_board_init,
    rsp_set_carrier,
    rsp_pid_config,
    rsp_pid_start,
    rsp_pid_hold,
    rsp_pid_release,
)
from catseq.compilation.compiler import compile_to_oasm_calls  # noqa: E402
from catseq.compilation.types import OASMAddress, OASMFunction  # noqa: E402
from catseq.hardware import rsp  # noqa: E402
from catseq.types import Board, Channel, ChannelType  # noqa: E402
from catseq.types.common import OperationType  # noqa: E402
from catseq.types.rsp import (  # noqa: E402
    RSPPIDActive,
    RSPPIDConfig,
    RSPPIDReady,
    RSPReady,
    RSPUninitialized,
    RSPWaveformParams,
)


def _rsp_channel():
    return Channel(Board("rsp6"), 0, ChannelType.RSP)


def test_rsp_atomic_pid_state_transitions_and_operation_types():
    ch = _rsp_channel()
    cfg = RSPPIDConfig(adc_in=0, rf_out=1, dgt_source=1, setpoint=0.25)

    init_op = rsp_board_init(ch).lanes[ch].operations[0]
    assert init_op.operation_type is OperationType.RSP_INIT
    assert init_op.start_state == RSPUninitialized()
    assert init_op.end_state == RSPReady()

    carrier_op = rsp_set_carrier(ch, 80.0).lanes[ch].operations[0]
    assert carrier_op.operation_type is OperationType.RSP_SET_CARRIER
    assert carrier_op.start_state == RSPReady()
    assert carrier_op.end_state == RSPReady(80.0)

    config_op = rsp_pid_config(ch, cfg, RSPReady()).lanes[ch].operations[0]
    assert config_op.operation_type is OperationType.RSP_PID_CONFIG
    assert config_op.start_state == RSPReady()
    assert config_op.end_state == RSPPIDReady(cfg)

    start_op = rsp_pid_start(ch, RSPPIDReady(cfg)).lanes[ch].operations[0]
    assert start_op.operation_type is OperationType.RSP_PID_START
    assert start_op.end_state == RSPPIDActive(cfg, hold=False)

    hold_op = rsp_pid_hold(ch, RSPPIDActive(cfg, hold=False)).lanes[ch].operations[0]
    assert hold_op.operation_type is OperationType.RSP_PID_HOLD
    assert hold_op.end_state == RSPPIDActive(cfg, hold=True)

    release_op = rsp_pid_release(ch, RSPPIDActive(cfg, hold=True)).lanes[ch].operations[0]
    assert release_op.operation_type is OperationType.RSP_PID_RELEASE
    assert release_op.end_state == RSPPIDActive(cfg, hold=False)


def test_rsp_pid_compilation_uses_dgt_source_not_channel_id():
    ch = _rsp_channel()
    cfg = RSPPIDConfig(adc_in=0, rf_out=1, dgt_source=3, setpoint=0.25)
    morphism = (
        rsp_board_init(ch)
        >> rsp_set_carrier(ch, 80.0)
        >> rsp_pid_config(ch, cfg, RSPReady())
        >> rsp_pid_start(ch, RSPPIDReady(cfg))
        >> rsp_pid_hold(ch, RSPPIDActive(cfg, hold=False))
        >> rsp_pid_release(ch, RSPPIDActive(cfg, hold=True))
    )

    calls = compile_to_oasm_calls(morphism)
    funcs_and_args = [(call.dsl_func, call.args) for call in calls[OASMAddress.RSP6]]

    assert (OASMFunction.RSP_INIT, ()) in funcs_and_args
    assert (OASMFunction.RSP_SET_CARRIER, (0, 80.0)) in funcs_and_args
    assert (OASMFunction.RSP_PID_CONFIG, (cfg,)) in funcs_and_args
    assert (OASMFunction.RSP_PID_START, (3,)) in funcs_and_args
    assert (OASMFunction.RSP_PID_HOLD, (3,)) in funcs_and_args
    assert (OASMFunction.RSP_PID_RELEASE, (3,)) in funcs_and_args


def test_rsp_high_level_defs_build_default_pid_config_sequence():
    ch = _rsp_channel()

    seq_def = (
        rsp.initialize(80.0)
        >> rsp.pid_config(ai_channel=0, ao_channel=1, setpoint=0.4, kp=-0.8, ki=-0.03)
        >> rsp.pid_start()
        >> rsp.pid_hold()
        >> rsp.pid_release()
    )
    morphism = seq_def(ch)
    ops = morphism.lanes[ch].operations

    assert [op.operation_type for op in ops] == [
        OperationType.RSP_INIT,
        OperationType.IDENTITY,
        OperationType.RSP_SET_CARRIER,
        OperationType.RSP_PID_CONFIG,
        OperationType.RSP_PID_START,
        OperationType.RSP_PID_HOLD,
        OperationType.RSP_PID_RELEASE,
    ]
    assert ops[3].end_state.config == RSPPIDConfig(
        adc_in=0,
        rf_out=1,
        dgt_source=1,
        setpoint=0.4,
        kp=-0.8,
        ki=-0.03,
        kd=0.0,
        output_max=0.01,
    )


def test_rsp_rf_config_builds_static_rf_state_and_compiler_call():
    ch = _rsp_channel()
    params = RSPWaveformParams(rf_out=0, amp=0.6, output_max=0.02)

    morphism = rsp.rf_config(params)(ch, RSPReady(carrier_freq=80.0))
    op = morphism.lanes[ch].operations[0]

    assert op.operation_type is OperationType.RSP_RF_CONFIG
    assert op.start_state == RSPReady(carrier_freq=80.0)
    assert op.end_state == RSPReady(carrier_freq=80.0, static_rf=params)

    calls = compile_to_oasm_calls(morphism)
    assert calls[OASMAddress.RSP6] == [
        # RSP static RF output should compile to exactly one RF_CONFIG call.
        type(calls[OASMAddress.RSP6][0])(
            adr=OASMAddress.RSP6,
            dsl_func=OASMFunction.RSP_RF_CONFIG,
            args=(params,),
        )
    ]


def test_compiler_rsp_static_rf_occupancy_time():
    ch = _rsp_channel()
    params = RSPWaveformParams(rf_out=0, amp=0.6)
    cfg = RSPPIDConfig(adc_in=0, rf_out=0, dgt_source=0, setpoint=0.25)

    morphism = (
        rsp.rf_config(params)
        >> hold(1 * us)
        >> rsp.pid_config(config=cfg)
    )(ch, RSPReady(carrier_freq=80.0))

    calls = compile_to_oasm_calls(morphism)
    funcs_and_args = [(call.dsl_func, call.args) for call in calls[OASMAddress.RSP6]]

    assert funcs_and_args == [
        (OASMFunction.RSP_RF_CONFIG, (params,)),
        (OASMFunction.WAIT, (250 - 13,)),
        (OASMFunction.RSP_PID_CONFIG, (cfg,)),
    ]
