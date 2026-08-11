"""Logical resources shared by the frontend demo programs.

The source programs refer only to these logical resources.  They never split a
program into per-board instruction streams; target lowering owns that work.
"""

from catseq.types import Board, Channel, ChannelType, StaticWaveform


controller = Board("main")
board_a = Board("rwg0")
board_b = Board("rwg1")

# Board A hosts a correction output and one waveform generator. Detector handles
# live in support.detectors because that public frontend surface is proposed.
correction_a = Channel(board_a, local_id=1, channel_type=ChannelType.TTL)
readout_a = Channel(board_a, local_id=2, channel_type=ChannelType.TTL)
rwg_a = Channel(board_a, local_id=0, channel_type=ChannelType.RWG)

# Board B supplies independent timing lanes used by the cross-board examples.
trigger_b = Channel(board_b, local_id=0, channel_type=ChannelType.TTL)
correction_b = Channel(board_b, local_id=1, channel_type=ChannelType.TTL)
readout_b = Channel(board_b, local_id=2, channel_type=ChannelType.TTL)
rwg_b = Channel(board_b, local_id=0, channel_type=ChannelType.RWG)

readout_waveform = StaticWaveform(freq=80.0, amp=0.2, sbg_id=0)
correction_waveform = StaticWaveform(freq=82.0, amp=0.1, sbg_id=1)
