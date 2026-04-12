"""
RWG-specific realization helpers for CatSeq V2.
"""

from __future__ import annotations

from typing import Mapping

from catseq.types.rwg import RWGActive, StaticWaveform, WaveformParams

from ..expr.realize import register_realizer, realize_value
from ..expr.types import ValueLike


def realize_static_waveform(
    value: StaticWaveform,
    state: ValueLike,
    env: Mapping[str, object] | None = None,
) -> StaticWaveform:
    return StaticWaveform(
        sbg_id=realize_value(value.sbg_id, state, env),
        freq=realize_value(value.freq, state, env),
        amp=realize_value(value.amp, state, env),
        phase=realize_value(value.phase, state, env),
        fct=realize_value(value.fct, state, env),
    )


def realize_waveform_params(
    value: WaveformParams,
    state: ValueLike,
    env: Mapping[str, object] | None = None,
) -> WaveformParams:
    return WaveformParams(
        sbg_id=realize_value(value.sbg_id, state, env),
        freq_coeffs=tuple(realize_value(value.freq_coeffs, state, env)),
        amp_coeffs=tuple(realize_value(value.amp_coeffs, state, env)),
        initial_phase=realize_value(value.initial_phase, state, env),
        phase_reset=realize_value(value.phase_reset, state, env),
        fct=realize_value(value.fct, state, env),
    )


def realize_rwg_active(
    value: RWGActive,
    state: ValueLike,
    env: Mapping[str, object] | None = None,
) -> RWGActive:
    snapshot = realize_value(value.snapshot, state, env)
    pending = realize_value(value.pending_waveforms, state, env)

    if isinstance(snapshot, list):
        snapshot = tuple(snapshot)
    if isinstance(pending, list):
        pending = tuple(pending)

    if isinstance(snapshot, tuple):
        snapshot = tuple(sorted(snapshot, key=lambda wf: wf.sbg_id))
    if isinstance(pending, tuple):
        pending = tuple(sorted(pending, key=lambda wf: wf.sbg_id))

    return RWGActive(
        carrier_freq=realize_value(value.carrier_freq, state, env),
        rf_on=realize_value(value.rf_on, state, env),
        snapshot=snapshot,
        pending_waveforms=pending,
    )


register_realizer(StaticWaveform, realize_static_waveform)
register_realizer(WaveformParams, realize_waveform_params)
register_realizer(RWGActive, realize_rwg_active)
