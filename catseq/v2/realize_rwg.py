"""
RWG-specific realization helpers for CatSeq V2.
"""

from __future__ import annotations

from catseq.types.rwg import RWGActive, StaticWaveform, WaveformParams

from .realize import register_realizer, realize_value
from .typing import ValueLike


def realize_static_waveform(value: StaticWaveform, state: ValueLike) -> StaticWaveform:
    return StaticWaveform(
        sbg_id=realize_value(value.sbg_id, state),
        freq=realize_value(value.freq, state),
        amp=realize_value(value.amp, state),
        phase=realize_value(value.phase, state),
        fct=realize_value(value.fct, state),
    )


def realize_waveform_params(value: WaveformParams, state: ValueLike) -> WaveformParams:
    return WaveformParams(
        sbg_id=realize_value(value.sbg_id, state),
        freq_coeffs=tuple(realize_value(value.freq_coeffs, state)),
        amp_coeffs=tuple(realize_value(value.amp_coeffs, state)),
        initial_phase=realize_value(value.initial_phase, state),
        phase_reset=realize_value(value.phase_reset, state),
        fct=realize_value(value.fct, state),
    )


def realize_rwg_active(value: RWGActive, state: ValueLike) -> RWGActive:
    snapshot = realize_value(value.snapshot, state)
    pending = realize_value(value.pending_waveforms, state)

    if isinstance(snapshot, list):
        snapshot = tuple(snapshot)
    if isinstance(pending, list):
        pending = tuple(pending)

    if isinstance(snapshot, tuple):
        snapshot = tuple(sorted(snapshot, key=lambda wf: wf.sbg_id))
    if isinstance(pending, tuple):
        pending = tuple(sorted(pending, key=lambda wf: wf.sbg_id))

    return RWGActive(
        carrier_freq=realize_value(value.carrier_freq, state),
        rf_on=realize_value(value.rf_on, state),
        snapshot=snapshot,
        pending_waveforms=pending,
    )


register_realizer(StaticWaveform, realize_static_waveform)
register_realizer(WaveformParams, realize_waveform_params)
register_realizer(RWGActive, realize_rwg_active)
