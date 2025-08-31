import pytest

# These imports are expected to work after setup.sh is run
from oasm.rtmq2.intf import sim_intf
from oasm.dev.main import C_MAIN, run_cfg, asm
from oasm.dev.rwg import C_RWG

def test_oasm_imports_and_instantiation():
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

test_oasm_imports_and_instantiation()