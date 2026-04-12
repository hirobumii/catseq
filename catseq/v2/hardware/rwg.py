"""
RWG helpers for CatSeq V2.
"""

from __future__ import annotations

from typing import List, Optional

from catseq.types.common import OperationType
from catseq.types.rwg import RWGActive, RWGReady, RWGUninitialized, StaticWaveform, WaveformParams

from . import realize_rwg as _realize_rwg  # noqa: F401
from ..morphism import Morphism, wait


def initialize(carrier_freq: float) -> Morphism:
    return Morphism.atomic(
        OperationType.RWG_INIT,
        state_requirement=RWGUninitialized,
        end_state=RWGUninitialized(),
    ) >> Morphism.atomic(
        OperationType.RWG_SET_CARRIER,
        state_requirement=(RWGUninitialized, RWGReady),
        end_state=RWGReady(carrier_freq=carrier_freq),
    )


def set_state(targets: List[StaticWaveform], phase_reset: bool = True) -> Morphism:
    params = [
        WaveformParams(
            sbg_id=t.sbg_id,
            freq_coeffs=(t.freq, 0.0, None, None),
            amp_coeffs=(t.amp, 0.0, None, None),
            initial_phase=t.phase,
            phase_reset=phase_reset,
            fct=t.fct,
        )
        for t in targets
    ]

    def _load_end(start_state):
        carrier_freq = start_state.carrier_freq
        rf_on = start_state.rf_on if isinstance(start_state, RWGActive) else False
        snapshot = start_state.snapshot if isinstance(start_state, RWGActive) else ()
        return RWGActive(
            carrier_freq=carrier_freq,
            rf_on=rf_on,
            snapshot=snapshot,
            pending_waveforms=tuple(params),
        )

    def _final_end(start_state):
        carrier_freq = start_state.carrier_freq
        rf_on = start_state.rf_on if isinstance(start_state, RWGActive) else False
        return RWGActive(
            carrier_freq=carrier_freq,
            rf_on=rf_on,
            snapshot=tuple(targets),
            pending_waveforms=None,
        )

    return Morphism.atomic(
        OperationType.RWG_LOAD_COEFFS,
        state_requirement=(RWGReady, RWGActive),
        end_state_factory=_load_end,
    ) >> Morphism.atomic(
        OperationType.RWG_UPDATE_PARAMS,
        state_requirement=RWGActive,
        end_state_factory=_final_end,
    )


def rf_on() -> Morphism:
    return Morphism.atomic(
        OperationType.RWG_RF_SWITCH,
        state_requirement=(RWGReady, RWGActive),
        end_state_factory=lambda start_state: RWGActive(
            carrier_freq=start_state.carrier_freq,
            rf_on=True,
            snapshot=start_state.snapshot if isinstance(start_state, RWGActive) else (),
            pending_waveforms=start_state.pending_waveforms if isinstance(start_state, RWGActive) else None,
        ),
    )


def rf_off() -> Morphism:
    return Morphism.atomic(
        OperationType.RWG_RF_SWITCH,
        state_requirement=RWGActive,
        end_state_factory=lambda start_state: RWGActive(
            carrier_freq=start_state.carrier_freq,
            rf_on=False,
            snapshot=start_state.snapshot,
            pending_waveforms=start_state.pending_waveforms,
        ),
    )


def rf_pulse(duration: float) -> Morphism:
    return rf_on() >> wait(duration) >> rf_off()


def linear_ramp(targets: List[Optional[StaticWaveform]], duration: float) -> Morphism:
    duration_us = duration * 1e6
    if duration_us <= 0:
        raise ValueError("Ramp duration must be positive.")

    def _derive_ramp(start_state: RWGActive) -> tuple[list[WaveformParams], list[StaticWaveform]]:
        if len(targets) != len(start_state.snapshot):
            raise ValueError(
                f"The number of targets ({len(targets)}) must match the number of active SBGs "
                f"({len(start_state.snapshot)})."
            )
        resolved_targets: list[StaticWaveform] = []
        ramp_params: list[WaveformParams] = []
        for target, current in zip(targets, start_state.snapshot):
            if target is not None and target.fct is not None and current.fct is not None and target.fct != current.fct:
                raise ValueError(
                    f"Target fct ({target.fct}) does not match current waveform fct ({current.fct}) "
                    f"for SBG {current.sbg_id}."
                )
            sbg_id = target.sbg_id if target and target.sbg_id is not None else current.sbg_id
            target_freq = target.freq if target and target.freq is not None else current.freq
            target_amp = target.amp if target and target.amp is not None else current.amp
            target_phase = target.phase if target else current.phase
            target_fct = target.fct if target and target.fct is not None else current.fct
            freq_rate = (target_freq - current.freq) / duration_us
            amp_rate = (target_amp - current.amp) / duration_us
            ramp_params.append(
                WaveformParams(
                    sbg_id=sbg_id,
                    freq_coeffs=(current.freq, freq_rate, None, None),
                    amp_coeffs=(current.amp, amp_rate, None, None),
                    initial_phase=current.phase,
                    phase_reset=False,
                    fct=current.fct,
                )
            )
            resolved_targets.append(
                StaticWaveform(
                    sbg_id=sbg_id,
                    freq=target_freq,
                    amp=target_amp,
                    phase=target_phase,
                    fct=target_fct,
                )
            )
        return ramp_params, resolved_targets

    def _ramp_end(start_state: RWGActive) -> RWGActive:
        ramp_params, _ = _derive_ramp(start_state)
        return RWGActive(
            carrier_freq=start_state.carrier_freq,
            rf_on=start_state.rf_on,
            snapshot=start_state.snapshot,
            pending_waveforms=tuple(ramp_params),
        )

    def _final_end(start_state: RWGActive) -> RWGActive:
        _, resolved_targets = _derive_ramp(start_state)
        return RWGActive(
            carrier_freq=start_state.carrier_freq,
            rf_on=start_state.rf_on,
            snapshot=tuple(resolved_targets),
            pending_waveforms=None,
        )

    return (
        Morphism.atomic(
            OperationType.RWG_LOAD_COEFFS,
            state_requirement=RWGActive,
            end_state_factory=_ramp_end,
        )
        >> Morphism.atomic(
            OperationType.RWG_UPDATE_PARAMS,
            state_requirement=RWGActive,
            end_state_factory=_ramp_end,
        )
        >> wait(duration)
        >> Morphism.atomic(
            OperationType.RWG_LOAD_COEFFS,
            state_requirement=RWGActive,
            end_state_factory=_final_end,
        )
        >> Morphism.atomic(
            OperationType.RWG_UPDATE_PARAMS,
            state_requirement=RWGActive,
            end_state_factory=_final_end,
        )
    )
