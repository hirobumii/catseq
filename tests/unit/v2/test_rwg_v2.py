from catseq.time_utils import us
from catseq.types.common import Board, Channel, ChannelType
from catseq.types.rwg import RWGActive, RWGReady, RWGUninitialized, StaticWaveform
from catseq.v2 import rwg as rwg_v2


def test_linear_ramp_uses_previous_state_when_materialized():
    ch = Channel(Board("rwg0"), 0, ChannelType.RWG)
    start = RWGActive(
        carrier_freq=100.0,
        rf_on=False,
        snapshot=(StaticWaveform(sbg_id=0, freq=10.0, amp=0.2, phase=0.0, fct=0),),
        pending_waveforms=None,
    )
    target = [StaticWaveform(sbg_id=0, freq=20.0, amp=0.6, phase=0.0, fct=0)]

    legacy, end_states = rwg_v2.linear_ramp(target, 5 * us).on(ch).materialize_with_states(start)

    ops = legacy.lanes[ch].operations
    assert len(ops) == 5
    assert ops[0].end_state.pending_waveforms[0].freq_coeffs[0] == 10.0
    assert ops[0].end_state.pending_waveforms[0].amp_coeffs[0] == 0.2
    assert end_states[ch].snapshot[0].freq == 20.0
    assert end_states[ch].snapshot[0].amp == 0.6


def test_initialize_materializes_from_uninitialized_like_state_chain():
    ch = Channel(Board("rwg0"), 0, ChannelType.RWG)

    legacy, end_states = rwg_v2.initialize(120.0).on(ch).materialize_with_states(RWGUninitialized())

    assert ch in legacy.lanes
    assert isinstance(end_states[ch], RWGReady)
    assert end_states[ch].carrier_freq == 120.0
