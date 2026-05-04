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
from catseq.compilation.compiler import compile_to_oasm_calls  # noqa: E402
from catseq.compilation.timing_analysis import static_operation_cost  # noqa: E402
from catseq.compilation.types import OASMAddress, OASMFunction  # noqa: E402
from catseq.hardware import rsp  # noqa: E402
from catseq.types import Board, Channel, ChannelType  # noqa: E402
from catseq.types.common import OperationType  # noqa: E402
from catseq.types.rsp import RSPPIDConfig, RSPReady, RSPWaveformParams  # noqa: E402


def _rsp_channel():
    return Channel(Board("rsp6"), 0, ChannelType.RSP)


def test_compiler_rsp_static_cost_table_contains_rsp_occupancies():
    assert static_operation_cost(OperationType.RSP_RF_CONFIG) == 13
    assert static_operation_cost(OperationType.RSP_PID_CONFIG) == 39


def test_compiler_rsp_static_rf_occupancy_reduces_following_wait():
    ch = _rsp_channel()
    params = RSPWaveformParams(rf_out=0, amp=0.6)
    cfg = RSPPIDConfig(adc_in=0, rf_out=0, dgt_source=0, setpoint=0.25)

    morphism = (
        rsp.rf_config(params)
        >> hold(1 * us)
        >> rsp.pid_config(config=cfg)
    )(ch, RSPReady(carrier_freq=80.0))

    events = compile_to_oasm_calls(morphism, _return_internal_events=True)[OASMAddress.RSP6]
    assert [(event.operation.operation_type, event.timestamp_cycles, event.cost_cycles) for event in events] == [
        (OperationType.RSP_RF_CONFIG, 0, 13),
        (OperationType.RSP_PID_CONFIG, 250, 39),
    ]

    calls = compile_to_oasm_calls(morphism)[OASMAddress.RSP6]
    assert [(call.dsl_func, call.args) for call in calls] == [
        (OASMFunction.RSP_RF_CONFIG, (params,)),
        (OASMFunction.WAIT, (250 - 13,)),
        (OASMFunction.RSP_PID_CONFIG, (cfg,)),
    ]
