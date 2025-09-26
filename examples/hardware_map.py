# examples/hardware_map.py

from catseq.types.common import Board, Channel, ChannelType

# 1. Define physical boards
main = Board(id="main")
rwg0 = Board(id="rwg0")
rwg1 = Board(id="rwg1")
rwg2 = Board(id="rwg2")
rwg3 = Board(id="rwg3")
rwg4 = Board(id="rwg4")
rwg5 = Board(id="rwg5")

# 2. Define specific channels on the boards

mot_repump = Channel(board=rwg0, local_id=0, channel_type=ChannelType.RWG)
mot_cooling = Channel(board=rwg0, local_id=1, channel_type=ChannelType.RWG)
cooling_lock = Channel(board=rwg4, local_id=0, channel_type=ChannelType.RWG)
global_imaging = Channel(board=rwg0, local_id=2, channel_type=ChannelType.RWG)
global_repump = Channel(board=rwg0, local_id=3, channel_type=ChannelType.RWG)

uv_led = Channel(board=rwg0, local_id=3, channel_type=ChannelType.TTL)
sync = Channel(board=main, local_id=0, channel_type=ChannelType.TTL)
artiq_trig = Channel(board=rwg1, local_id=0, channel_type=ChannelType.TTL)
gradient_mag = Channel(board=rwg0, local_id=0, channel_type=ChannelType.TTL)
mag_trig = Channel(board=rwg0, local_id=1, channel_type=ChannelType.TTL)
qcmos_trig = Channel(board=rwg0, local_id=2, channel_type=ChannelType.TTL)

blowoff = Channel(board=rwg1, local_id=0, channel_type=ChannelType.RWG)
eit1 = Channel(board=rwg1, local_id=1, channel_type=ChannelType.RWG)
eit2 = Channel(board=rwg1, local_id=2, channel_type=ChannelType.RWG)
local_repump = Channel(board=rwg1, local_id=3, channel_type=ChannelType.RWG)

local_image1 = Channel(board=rwg2, local_id=0, channel_type=ChannelType.RWG)
local_image2 = Channel(board=rwg2, local_id=1, channel_type=ChannelType.RWG)
local_image_total = Channel(board=rwg2, local_id=2, channel_type=ChannelType.RWG)

cooling_shutter = Channel(board=rwg2, local_id=0, channel_type=ChannelType.TTL)
mot_repump_shutter = Channel(board=rwg2, local_id=1, channel_type=ChannelType.TTL)
global_imaging_shutter = Channel(board=rwg2, local_id=2, channel_type=ChannelType.TTL)
blowoff_shutter = Channel(board=rwg2, local_id=3, channel_type=ChannelType.TTL)
global_repump_shutter = Channel(board=rwg1, local_id=2, channel_type=ChannelType.TTL)


global_raman = Channel(board=rwg3, local_id=0, channel_type=ChannelType.RWG)

sqg_i = Channel(board=rwg5, local_id=0, channel_type=ChannelType.RWG)
sqg_q = Channel(board=rwg5, local_id=1, channel_type=ChannelType.RWG)
mw_sw = Channel(board=rwg5, local_id=0, channel_type=ChannelType.TTL)
test = Channel(rwg5, local_id=2, channel_type=ChannelType.RWG)


channel_styles = {
    sync: {"style": "default", "name": "Sync"},

    cooling_lock: {"style": "freq", "name": "Cooling Lock"},

    mot_repump: {"style": "default", "name": "Mot Repump"},
    mot_cooling: {"style": "amp", "name": "MOT Cooling"},

    global_imaging: {"style": "default", "name": "Global Imaging"},
    global_repump: {"style": "default", "name": "Global Repump"},
    blowoff: {"style": "amp", "name": "Blowoff & Pumping"},

    eit1: {"style": "default", "name": "EIT 1"},
    eit2: {"style": "default", "name": "EIT 2"},
    local_repump: {"style": "default", "name": "Local Repump"},
    local_image1: {"style": "default", "name": "Local Image1"},
    local_image2: {"style": "default", "name": "Local Image2"},
    local_image_total: {"style": "default", "name": "Local Image Total"},

    uv_led: {"style": "default", "name": "UV Led"},
    artiq_trig: {"style": "default", "name": "Artiq Trig"},
    gradient_mag: {"style": "default", "name": "Gradient Mag"},
    mag_trig: {"style": "default", "name": "Mag Trig"},
    qcmos_trig: {"style": "default", "name": "Qcmos Trig"},

    cooling_shutter: {"style": "default", "name": "Cooling Shutter"},
    mot_repump_shutter: {"style": "default", "name": "MOT Repump Shutter"},
    global_imaging_shutter: {"style": "default", "name": "Global Imaging Shutter"},
    blowoff_shutter: {"style": "default", "name": "Blowoff Shutter"},
    global_repump_shutter: {"style": "default", "name": "Global Repump Shutter"},

    sqg_i: {"style": "default", "name": "SQG I"},
    sqg_q: {"style": "default", "name": "SQG Q"},
    mw_sw: {"style": "default", "name": "Microwave Switch"}
}