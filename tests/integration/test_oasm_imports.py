"""Smoke-test the OASM dependency used by the Python host adapter."""

from oasm.dev.main import C_MAIN, run_cfg
from oasm.dev.rwg import C_RWG, rwg
from oasm.rtmq2 import assembler, disassembler
from oasm.rtmq2.intf import sim_intf


def test_oasm_assembler_accepts_a_catseq_host_callback() -> None:
    interface = sim_intf()
    interface.nod_adr = 0
    interface.loc_chn = 1
    run_all = run_cfg(interface, [1, 0])
    sequence = assembler(run_all, [("rwg0", C_RWG), ("main", C_MAIN)])

    def uv_off() -> None:
        rwg.ttl.off(1)

    sequence("rwg0", uv_off)

    assert disassembler(core=C_RWG)(sequence.asm["rwg0"])
