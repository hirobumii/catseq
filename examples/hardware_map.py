# examples/hardware_map.py

from catseq.types.common import Board, Channel, ChannelType

# 1. Define physical boards
main = Board(id="main")
rwg0 = Board(id="rwg0")
rwg1 = Board(id="rwg1")
rwg4 = Board(id="rwg4")

# 2. Define specific channels on the boards

mot_repump = Channel(board=rwg0, local_id=0, channel_type=ChannelType.RWG)
mot_cooling = Channel(board=rwg0, local_id=1, channel_type=ChannelType.RWG)
cooling_lock = Channel(board=rwg4, local_id=0, channel_type=ChannelType.RWG)
global_imaging = Channel(board=rwg0, local_id=2, channel_type=ChannelType.RWG)
global_repump = Channel(board=rwg0, local_id=3, channel_type=ChannelType.RWG)

uv_led = Channel(board=rwg0, local_id=0, channel_type=ChannelType.TTL)

