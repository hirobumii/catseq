from hardware_map import (
    mot_cooling,
    mot_repump,
    global_imaging,
    global_repump,
    cooling_lock,
    uv_led,
    sync,
    trig_artiq
)

from catseq.hardware.sync import global_sync
from catseq.hardware.ttl import pulse, initialize_channel
from catseq.hardware.rwg import initialize, set_state, identity, rf_on, rf_off, InitialTarget
from catseq.compilation.compiler import compile_to_oasm_calls, execute_oasm_calls
from catseq.morphism import Morphism
from catseq.types.common import Channel, State
from oasm.rtmq2.intf import sim_intf, ft601_intf
from oasm.rtmq2 import assembler
from oasm.dev.main import run_cfg, C_MAIN
from oasm.dev.rwg import C_RWG


trig_uv_led = pulse(uv_led, 5.0)
sync_init = initialize_channel(sync)

# rwg0_init = rwg_board_init(mot_cooling)

# cooling_car = rwg_set_carrier(mot_cooling, 95)
# repump_car = rwg_set_carrier(mot_repump, 71)
# global_repump_car = rwg_set_carrier(global_repump, 71)
# global_imaging_car = rwg_set_carrier(global_imaging, 95)

def get_end_state(morphism: Morphism, channel: Channel)->State | None:
    return morphism.lanes[channel].operations[-1].end_state

mot_cooling_init = initialize(95)(mot_cooling)
mot_repump_init = initialize(71)(mot_repump)
global_imaging_init = initialize(95)(global_imaging)
global_repump_init = initialize(71)(global_repump)

laser_init = sync_init | mot_cooling_init | mot_repump_init | global_imaging_init | global_repump_init
laser_init = laser_init >> identity(10.0)

cooling_target = InitialTarget(
    mot_cooling.local_id<<5,
    0.0,
    0.15
 )

repump_target = InitialTarget(
    mot_repump.local_id<<5,
    0.0,
    0.15
)

global_imaging_target = InitialTarget(
    global_imaging.local_id<<5,
    0.0,
    0.012
)

global_repump_target = InitialTarget(
    global_repump.local_id<<5,
    0.0,
    0.077
)


para_init = set_state([cooling_target])(mot_cooling, get_end_state(laser_init, mot_cooling)) \
    | set_state([repump_target])(mot_repump, get_end_state(laser_init, mot_repump)) \
    | set_state([global_imaging_target])(global_imaging, get_end_state(laser_init, global_imaging)) \
    | set_state([global_repump_target])(global_repump, get_end_state(laser_init, global_repump))

morphism = laser_init >> para_init >> identity(100.0)

rf_all_on = rf_on()(mot_cooling, get_end_state(morphism, mot_cooling)) \
    | rf_on()(mot_repump, get_end_state(morphism, mot_repump))
    # | rf_on()(global_imaging, get_end_state(morphism, global_imaging)) \
    # | rf_on()(global_repump, get_end_state(morphism, global_repump))

rf_all_off = rf_off()(mot_cooling, get_end_state(morphism, mot_cooling)) \
    | rf_off()(mot_repump, get_end_state(morphism, mot_repump)) \
    | rf_off()(global_imaging, get_end_state(morphism, global_imaging)) \
    | rf_off()(global_repump, get_end_state(morphism, global_repump))

morphism = morphism >> global_sync() >> identity(10.0) >> rf_all_off

# intf_usb = sim_intf()
intf_usb = ft601_intf("IONCV2PROT")#;intf_usb.__enter__()
intf_usb.nod_adr = 0
intf_usb.loc_chn = 1

rwgs = [1,2,3,4,5]
run_all = run_cfg(intf_usb, rwgs+[0])
seq = assembler(run_all,[(f'rwg{i}', C_RWG) for i in range(len(rwgs))]+[('main',C_MAIN)])

oasm_calls = compile_to_oasm_calls(morphism, seq)
a,b = execute_oasm_calls(oasm_calls, seq)
