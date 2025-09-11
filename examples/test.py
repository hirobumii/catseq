from hardware_map import (
    mot_cooling,
    mot_repump,
    global_imaging,
    global_repump,
    cooling_lock,
    uv_led,
    sync,
    mag_trig,
    gradient_mag,
    qcmos_trig,
    artiq_trig
)

from catseq.hardware.sync import global_sync
from catseq.hardware.ttl import pulse, initialize_channel, set_high, set_low
from catseq.hardware.rwg import initialize, set_state, identity, rf_on, rf_off, rf_pulse, linear_ramp, RWGTarget
from catseq.compilation.compiler import compile_to_oasm_calls, execute_oasm_calls
from catseq.morphism import Morphism
from catseq.types.common import Channel, State
from catseq.types.ttl import TTLState
from oasm.rtmq2.intf import sim_intf, ft601_intf
from oasm.rtmq2 import assembler
from oasm.dev.main import run_cfg, C_MAIN
from oasm.dev.rwg import C_RWG


trig_uv_led = pulse(uv_led, 5.0)

sync_init = initialize_channel(sync)
mag_trig_init = initialize_channel(mag_trig)
qcmos_trig_init = initialize_channel(qcmos_trig)
artiq_trig_init = initialize_channel(artiq_trig)
gradient_mag_init = initialize_channel(gradient_mag)


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
global_repump_init = initialize(80)(global_repump)

laser_init = mot_cooling_init | mot_repump_init | global_imaging_init | global_repump_init
trig_init = sync_init | mag_trig_init | qcmos_trig_init | artiq_trig_init | gradient_mag_init
all_init = (laser_init | trig_init) >> identity(10.0)

cooling_target = RWGTarget(
    0.0,
    0.15,
    mot_cooling.local_id<<5
 )

repump_target = RWGTarget(
    0.0,
    0.15,
    mot_repump.local_id<<5
)

global_imaging_target = RWGTarget(
    0.0,
    0.008,
    global_imaging.local_id<<5,
)

global_repump_target = RWGTarget(
    0.0,
    0.077,
    global_repump.local_id<<5,
)

cooling_locking_target = RWGTarget(
    0.0,
    0.1,
    cooling_lock.local_id<<5,
)

molasses_locking_target = RWGTarget(
    # cooling_lock.local_id<<5,
    1.0944,
    0.1
)

molasses_cooling_target = RWGTarget(
    # mot_cooling.local_id<<5,
    0.0,
    0.05
)

molasses_cooling_start_target = RWGTarget(
    0.0,
    0.10,
    mot_cooling.local_id<<5,
)


locking_morphism = initialize(204.96)(cooling_lock) >> identity(10.0) 
locking_morphism = locking_morphism >> set_state([cooling_locking_target])(cooling_lock, get_end_state(locking_morphism, cooling_lock))
locking_morphism = locking_morphism >> rf_on()(cooling_lock, get_end_state(locking_morphism, cooling_lock))

para_init = {
    mot_cooling: set_state([cooling_target]),
    mot_repump: set_state([repump_target]),
    global_imaging: set_state([global_imaging_target]),
    global_repump: set_state([global_repump_target])
}

# para_init = set_state([cooling_target])(mot_cooling, get_end_state(laser_init, mot_cooling)) \
#     | set_state([repump_target])(mot_repump, get_end_state(laser_init, mot_repump)) \
#     | set_state([global_imaging_target])(global_imaging, get_end_state(laser_init, global_imaging)) \
#     | set_state([global_repump_target])(global_repump, get_end_state(laser_init, global_repump))

init_morphism = all_init >> para_init >> identity(100.0)
init_morphism = init_morphism | locking_morphism

mot_laser_on = {
    mot_cooling: rf_on(),
    mot_repump: rf_on()
}
# mot_laser_on = rf_on()(mot_cooling, get_end_state(init_morphism, mot_cooling)) \
#     | rf_on()(mot_repump, get_end_state(init_morphism, mot_repump))
    # | rf_on()(global_imaging, get_end_state(init_morphism, global_imaging)) \
    # | rf_on()(global_repump, get_end_state(init_morphism, global_repump))

mot_laser_off = {
    mot_cooling: rf_off(),
    mot_repump: rf_off()
}
# mot_laser_off = rf_off()(mot_cooling, get_end_state(init_morphism, mot_cooling)) \
#     | rf_off()(mot_repump, get_end_state(init_morphism, mot_repump))

rf_all_off = {
    mot_cooling: rf_off(),
    mot_repump: rf_off(),
    global_imaging: rf_off(),
    global_repump: rf_off()
}

# rf_all_off = rf_off()(mot_cooling, get_end_state(init_morphism, mot_cooling)) \
#     | rf_off()(mot_repump, get_end_state(init_morphism, mot_repump)) \
#     | rf_off()(global_imaging, get_end_state(init_morphism, global_imaging)) \
#     | rf_off()(global_repump, get_end_state(init_morphism, global_repump))

mot_on = (mot_laser_on | pulse(uv_led, 10.0) | set_high(gradient_mag))

# morphism = init_morphism >> global_sync() >> identity(10.0) >> mot_on

# trigger = pulse(mag_trig, 10.0)

mot_morphism = (pulse(mag_trig,10.0) | mot_laser_on | pulse(uv_led, 10.0) | set_high(gradient_mag)) >> \
    identity(1000_000) >> (mot_laser_off | set_low(gradient_mag)|pulse(mag_trig,10.0)) 
mot_morphism = mot_morphism >> (set_state([molasses_cooling_start_target])(mot_cooling, get_end_state(mot_morphism, mot_cooling))) >> identity(10)

# morphism = init_morphism >> global_sync() >> identity(10.0) >> mot_on
morphism = init_morphism >> global_sync() >> identity(10.0) >> mot_morphism 


molasses_morphism = linear_ramp([molasses_locking_target], 10_000)(cooling_lock, get_end_state(morphism, cooling_lock)) \
    | (rf_on()>>linear_ramp([molasses_cooling_target], 10_000))(mot_cooling, get_end_state(morphism, mot_cooling)) \
    | rf_on()(mot_repump, get_end_state(morphism, mot_cooling))
molasses_morphism = molasses_morphism >> identity(10_000) >> (rf_off()(mot_cooling, get_end_state(molasses_morphism, mot_cooling))\
                                                             | rf_off()(mot_repump, get_end_state(molasses_morphism, mot_repump)))

molasses_morphism = molasses_morphism >> linear_ramp([cooling_locking_target], 5_000)(cooling_lock, get_end_state(molasses_morphism, cooling_lock))

morphism = morphism >> molasses_morphism >> identity(50_000.0)
# morphism = morphism >> identity(50_000.0)
artiq_trigger_morphism = pulse(artiq_trig, 10.0)

imaging_morphism = rf_pulse(30_000)(global_imaging, get_end_state(morphism, global_imaging)) \
    | rf_pulse(30_000)(global_repump, get_end_state(morphism, global_repump)) \
    | pulse(qcmos_trig, 10.0)
morphism = morphism >> imaging_morphism >> identity(50_000) >> artiq_trigger_morphism >> identity(50_000) >> imaging_morphism

# intf_usb = sim_intf()
intf_usb = ft601_intf("IONCV2PROT")#;intf_usb.__enter__()
intf_usb.nod_adr = 0
intf_usb.loc_chn = 1

rwgs = [1,2,3,4,5]
run_all = run_cfg(intf_usb, rwgs+[0])
seq = assembler(run_all,[(f'rwg{i}', C_RWG) for i in range(len(rwgs))]+[('main',C_MAIN)])