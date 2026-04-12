from dataclasses import dataclass

import pytest

from catseq.time_utils import us, ms
from catseq.types.common import Board, Channel, ChannelType
from catseq.types.rwg import RWGUninitialized, StaticWaveform
from catseq.types.ttl import TTLState
from catseq.v2.hardware import rwg as rwg_v2
from catseq.v2.hardware import ttl as ttl_v2
from catseq.v2.morphism import Morphism, hold


@dataclass(frozen=True)
class V2ReferenceExperimentContext:
    all_channels: list[Channel]
    artiq_trig: Channel
    global_imaging: Channel
    raman_sw: Channel

    def rwg_target(
        self, channel: Channel, freq: float, amp: float, phase: float = 0.0, fct: int = 0
    ) -> list[StaticWaveform]:
        return [
            StaticWaveform(
                sbg_id=channel.local_id << 5,
                freq=freq,
                amp=amp,
                phase=phase,
                fct=fct,
            )
        ]

    def idle_except(self, duration: float, *active_channels: Channel) -> Morphism:
        active = set(active_channels)
        idle_channels = [channel for channel in self.all_channels if channel not in active]
        if not idle_channels:
            raise ValueError("idle_except requires at least one idle channel to pad.")

        result = hold(duration).on(idle_channels[0])
        for channel in idle_channels[1:]:
            result = result | hold(duration).on(channel)
        return result

    def start_states(self) -> dict[Channel, TTLState | RWGUninitialized]:
        starts: dict[Channel, TTLState | RWGUninitialized] = {}
        for channel in self.all_channels:
            if channel.channel_type == ChannelType.TTL:
                starts[channel] = TTLState.UNINITIALIZED
            else:
                starts[channel] = RWGUninitialized()
        return starts

    def build(self) -> Morphism:
        (
            artiq_trig,
            mot_cooling,
            mot_repump,
            uv_led,
            cooling_lock,
            mag_trig,
            imaging_shutter,
            blowoff_shutter,
            global_imaging,
            sqg_i,
            sqg_q,
            raman_sw,
        ) = self.all_channels

        init = (
            ttl_v2.initialize().on(artiq_trig)
            | (rwg_v2.initialize(95.0) >> rwg_v2.set_state(self.rwg_target(mot_cooling, 0.0, 0.15))).on(mot_cooling)
            | (rwg_v2.initialize(71.0) >> rwg_v2.set_state(self.rwg_target(mot_repump, 0.0, 0.15))).on(mot_repump)
            | ttl_v2.initialize().on(uv_led)
            | ttl_v2.initialize().on(mag_trig)
            | (rwg_v2.initialize(110.0) >> rwg_v2.set_state(self.rwg_target(cooling_lock, 7.8, 0.2))).on(cooling_lock)
            | ttl_v2.initialize().on(imaging_shutter)
            | ttl_v2.initialize().on(blowoff_shutter)
            | (rwg_v2.initialize(140.0) >> rwg_v2.set_state(self.rwg_target(global_imaging, 12.0, 0.0))).on(global_imaging)
            | (rwg_v2.initialize(80.0) >> rwg_v2.set_state(self.rwg_target(sqg_i, -0.33, 0.2))).on(sqg_i)
            | (rwg_v2.initialize(80.0) >> rwg_v2.set_state(self.rwg_target(sqg_q, -0.33, 0.2, phase=1.57))).on(sqg_q)
            | ttl_v2.initialize().on(raman_sw)
        )

        mot_loading = (
            ttl_v2.pulse(10 * us).on(uv_led)
            | ttl_v2.pulse(10 * us).on(mag_trig)
            | (rwg_v2.rf_on() >> hold(20 * ms) >> rwg_v2.rf_off()).on(mot_cooling)
            | (rwg_v2.rf_on() >> hold(20 * ms) >> rwg_v2.rf_off()).on(mot_repump)
            | (rwg_v2.rf_on() >> hold(20 * ms) >> rwg_v2.rf_off()).on(cooling_lock)
            | self.idle_except(20 * ms, uv_led, mag_trig, mot_cooling, mot_repump, cooling_lock)
        )

        molasses = (
            (rwg_v2.linear_ramp(self.rwg_target(mot_cooling, 0.0, 0.03), 8 * ms) >> hold(2 * ms)).on(mot_cooling)
            | (rwg_v2.linear_ramp(self.rwg_target(cooling_lock, 7.6, 0.1), 8 * ms) >> hold(2 * ms)).on(cooling_lock)
            | self.idle_except(10 * ms, mot_cooling, cooling_lock)
        )

        optical_pumping = (
            ttl_v2.pulse(20 * us).on(imaging_shutter)
            | (rwg_v2.set_state(self.rwg_target(global_imaging, 12.5, 0.018)) >> rwg_v2.rf_pulse(10 * us)).on(global_imaging)
            | self.idle_except(20 * us, imaging_shutter, global_imaging)
        )

        clock_pulse = (
            ttl_v2.pulse(6 * us).on(raman_sw)
            | rwg_v2.rf_pulse(5 * us).on(sqg_i)
            | rwg_v2.rf_pulse(5 * us).on(sqg_q)
            | self.idle_except(6 * us, raman_sw, sqg_i, sqg_q)
        )

        blowoff = (
            ttl_v2.pulse(5 * ms).on(blowoff_shutter)
            | (rwg_v2.set_state(self.rwg_target(global_imaging, 12.8, 0.3)) >> rwg_v2.rf_pulse(5 * ms)).on(global_imaging)
            | self.idle_except(5 * ms, blowoff_shutter, global_imaging)
        )

        imaging = (
            ttl_v2.pulse(10 * us).on(artiq_trig)
            | ttl_v2.pulse(200 * us).on(imaging_shutter)
            | (rwg_v2.set_state(self.rwg_target(global_imaging, 11.5, 0.12)) >> rwg_v2.rf_pulse(200 * us)).on(global_imaging)
            | self.idle_except(200 * us, artiq_trig, imaging_shutter, global_imaging)
        )

        return (
            init
            >> mot_loading
            >> molasses
            >> optical_pumping
            >> self.idle_except(30 * ms)
            >> clock_pulse
            >> blowoff
            >> self.idle_except(200 * ms)
            >> imaging
        )


@pytest.fixture
def v2_reference_context() -> V2ReferenceExperimentContext:
    main = Board("main")
    rwg0 = Board("rwg0")
    rwg1 = Board("rwg1")
    rwg2 = Board("rwg2")
    rwg4 = Board("rwg4")
    rwg5 = Board("rwg5")

    artiq_trig = Channel(main, 0, ChannelType.TTL)
    mot_cooling = Channel(rwg0, 0, ChannelType.RWG)
    mot_repump = Channel(rwg0, 1, ChannelType.RWG)
    uv_led = Channel(rwg0, 3, ChannelType.TTL)
    cooling_lock = Channel(rwg1, 0, ChannelType.RWG)
    mag_trig = Channel(rwg1, 1, ChannelType.TTL)
    imaging_shutter = Channel(rwg2, 0, ChannelType.TTL)
    blowoff_shutter = Channel(rwg2, 1, ChannelType.TTL)
    global_imaging = Channel(rwg4, 0, ChannelType.RWG)
    sqg_i = Channel(rwg5, 0, ChannelType.RWG)
    sqg_q = Channel(rwg5, 1, ChannelType.RWG)
    raman_sw = Channel(rwg5, 2, ChannelType.TTL)

    all_channels = [
        artiq_trig,
        mot_cooling,
        mot_repump,
        uv_led,
        cooling_lock,
        mag_trig,
        imaging_shutter,
        blowoff_shutter,
        global_imaging,
        sqg_i,
        sqg_q,
        raman_sw,
    ]

    return V2ReferenceExperimentContext(
        all_channels=all_channels,
        artiq_trig=artiq_trig,
        global_imaging=global_imaging,
        raman_sw=raman_sw,
    )
