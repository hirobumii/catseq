import dataclasses
from typing import Tuple, Union, Optional, Dict
import numpy as np

from catseq.protocols import Channel, State
from catseq.model import PrimitiveMorphism, LaneMorphism
from catseq.builder import MorphismBuilder
from catseq.states.common import Uninitialized
from catseq.states.rwg import (
    RWGState,
    RWGReady,
    RWGActive,
    WaveformParams,
    StaticWaveform,
)

# A small tolerance for float comparisons in state validation.
_STATE_TOLERANCE = 1e-9

def _evaluate_waveforms_at_time(
    t: float,
    params_tuple: Tuple[WaveformParams, ...],
    start_phases: Dict[int, float],
) -> Tuple[StaticWaveform, ...]:
    """
    A pure function to calculate the instantaneous StaticWaveform tuple for a
    given time t, based on waveform parameters and explicit start phases.
    """
    static_waveforms = []
    for params in params_tuple:
        d0_f, d1_f, d2_f, d3_f = params.freq_coeffs
        d0_a, d1_a, d2_a, d3_a = params.amp_coeffs

        freq = d0_f + d1_f*t + d2_f*(t**2)/2.0 + d3_f*(t**3)/6.0
        amp = d0_a + d1_a*t + d2_a*(t**2)/2.0 + d3_a*(t**3)/6.0

        integral_term = 2 * np.pi * 1e6 * (
            d0_f*t +
            d1_f*(t**2)/2.0 +
            d2_f*(t**3)/6.0 +
            d3_f*(t**4)/24.0
        )

        start_phase = start_phases.get(params.sbg_id, 0.0)
        phase = (start_phase + integral_term) % (2 * np.pi)

        static_waveforms.append(
            StaticWaveform(sbg_id=params.sbg_id, freq=freq, amp=amp, phase=phase)
        )
    return tuple(sorted(static_waveforms, key=lambda wf: wf.sbg_id))


def play(
    duration: float,
    params: Tuple[WaveformParams, ...],
) -> MorphismBuilder:
    """
    Creates a deferred morphism to play a dynamic waveform segment on an RWG channel.
    """
    if duration <= 0:
        raise ValueError("Playback duration must be a positive number.")
    if not params:
        raise ValueError("WaveformParams tuple cannot be empty.")

    def generator(channel: Channel, from_state: State) -> LaneMorphism:
        if not isinstance(from_state, (RWGReady, RWGActive)):
            raise TypeError(
                f"RWG play() can only be called from a Ready or Active state, "
                f"not {type(from_state).__name__}."
            )

        start_phases: Dict[int, float] = {}
        from_waveforms_map = {
            wf.sbg_id: wf for wf in from_state.waveforms
        } if isinstance(from_state, RWGActive) else {}

        for p in params:
            if p.phase_reset:
                start_phases[p.sbg_id] = p.initial_phase or 0.0
            else:
                from_wf = from_waveforms_map.get(p.sbg_id)
                start_phases[p.sbg_id] = from_wf.phase if from_wf else (p.initial_phase or 0.0)

        if isinstance(from_state, RWGActive):
            initial_waveforms = _evaluate_waveforms_at_time(0.0, params, start_phases)
            initial_waveforms_map = {wf.sbg_id: wf for wf in initial_waveforms}

            for sbg_id, from_wf in from_waveforms_map.items():
                initial_wf = initial_waveforms_map.get(sbg_id)
                if not initial_wf:
                    raise ValueError(f"Continuity error: SBG {sbg_id} was active but is no longer defined.")
                if not np.isclose(from_wf.freq, initial_wf.freq, atol=_STATE_TOLERANCE):
                    raise ValueError(f"Frequency discontinuity on SBG {sbg_id}.")
                if not np.isclose(from_wf.amp, initial_wf.amp, atol=_STATE_TOLERANCE):
                    raise ValueError(f"Amplitude discontinuity on SBG {sbg_id}.")

        final_waveforms = _evaluate_waveforms_at_time(duration, params, start_phases)
        to_state = RWGActive(
            carrier_freq=from_state.carrier_freq,
            waveforms=final_waveforms,
        )

        m = PrimitiveMorphism(
            name=f"{channel.name}.play({len(params)} wfs)",
            dom=((channel, from_state),),
            cod=((channel, to_state),),
            duration=duration,
            dynamics=params,
        )
        return LaneMorphism.from_primitive(m)

    return MorphismBuilder(single_generator=generator)
