# examples/hardware_map.py

from catseq.types.common import Board, Channel, ChannelType

# 1. Define physical boards
main = Board(id="main")
rwg0 = Board(id="rwg0")
rwg1 = Board(id="rwg1")
rwg2 = Board(id="rwg2")
rwg4 = Board(id="rwg4")

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