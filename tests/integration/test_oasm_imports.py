import pytest

# These imports are expected to work after setup.sh is run
from oasm.rtmq2.intf import sim_intf
from oasm.rtmq2 import assembler, disassembler
from oasm.dev.main import C_MAIN, run_cfg
from oasm.dev.rwg import C_RWG, rwg

"""
Tests that necessary oasm modules can be imported and objects instantiated.
This test assumes that 'setup.sh' has been run to make 'oasm.dev.main'
and 'oasm.dev.rwg' importable.
"""

print("\n🧪 Testing OASM imports and instantiation...")

# Instantiate sim_intf
intf_usb = sim_intf()
intf_usb.nod_adr = 0
intf_usb.loc_chn = 1
print(f"✅ sim_intf instantiated: {intf_usb}")

# Define rwgs
rwgs = [1, 2, 3, 4, 5]
print(f"✅ rwgs defined: {rwgs}")

# Instantiate run_cfg objects
run_all = run_cfg(intf_usb, rwgs + [0])
print(f"✅ run_all (run_cfg) instantiated: {run_all}")

rwg_run = run_cfg(intf_usb, rwgs, core=C_RWG)
print(f"✅ rwg_run (run_cfg) instantiated: {rwg_run}")

print("🎉 All OASM imports and instantiations successful (assuming setup.sh was run).")


def uv_off():
    rwg.ttl.off(1)

seq = assembler(run_all,[(f'rwg{i}',C_RWG) for i in range(len(rwgs))]+[('main',C_MAIN)])
seq('rwg0', uv_off)
# seq.run(disa=True)
print(disassembler(core=C_RWG)(seq.asm['rwg0']))
