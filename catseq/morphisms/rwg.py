from typing import Tuple, Optional, Dict
import numpy as np

from catseq.protocols import Channel, State
from catseq.model import PrimitiveMorphism, LaneMorphism
from catseq.builder import MorphismBuilder
from catseq.states.common import Uninitialized
from catseq.states.rwg import (
    RWGReady,
    RWGActive,
    WaveformParams,
    StaticWaveform,
)

# A small tolerance for float comparisons in state validation.
_STATE_TOLERANCE = 1e-9

def _pad_coeffs(coeffs: Tuple[Optional[float], ...], target_length: int = 4) -> Tuple[float, ...]:
    """Pads a tuple of coefficients with zeros to a target length."""
    num_missing = target_length - len(coeffs)
    # Replace None with 0.0 before padding
    cleaned_coeffs = [c if c is not None else 0.0 for c in coeffs]
    return tuple(cleaned_coeffs + [0.0] * num_missing)

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
        d0_f, d1_f, d2_f, d3_f = _pad_coeffs(params.freq_coeffs)
        d0_a, d1_a, d2_a, d3_a = _pad_coeffs(params.amp_coeffs)

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


def initialize(
    carrier_freq: float,
    duration: float = 1e-6
) -> MorphismBuilder:
    """
    Creates a deferred morphism to initialize an RWG channel to a Ready state.
    """
    def generator(channel: Channel, from_state: State) -> LaneMorphism:
        if not isinstance(from_state, Uninitialized):
            raise TypeError(
                f"RWG initialize() can only be called from an Uninitialized state, "
                f"not {type(from_state).__name__}."
            )

        to_state = RWGReady(carrier_freq=carrier_freq)
        m = PrimitiveMorphism(
            name=f"{channel.name}.init({carrier_freq:.1f}MHz)",
            dom=((channel, from_state),),
            cod=((channel, to_state),),
            duration=duration,
        )
        return LaneMorphism.from_primitive(m)

    return MorphismBuilder(single_generator=generator)


def linear_ramp(
    duration: float,
    *,
    end_freqs: Tuple[float, ...],
    end_amps: Tuple[float, ...],
    start_freqs: Optional[Tuple[float, ...]] = None,
    start_amps: Optional[Tuple[float, ...]] = None,
    phase_resets: Optional[Tuple[bool, ...]] = None,
) -> MorphismBuilder:
    """
    A high-level factory to create a linear ramp for N tones on an RWG channel.

    The channel must have an `sbg_ids` attribute. The number of frequencies and
    amplitudes provided must match the number of sbg_ids on the channel.

    If start frequencies/amplitudes are not provided, they are inferred from
    the preceding morphism's state at composition time.
    """
    def generator(channel: Channel, from_state: State) -> LaneMorphism:
        if not hasattr(channel, "sbg_ids") or not channel.sbg_ids:
            raise TypeError("linear_ramp requires a channel with a non-empty 'sbg_ids' attribute.")

        sbg_ids = channel.sbg_ids
        num_tones = len(sbg_ids)

        if len(end_freqs) != num_tones:
            raise ValueError(f"Number of end_freqs ({len(end_freqs)}) must match the number of SBGs ({num_tones}).")
        if len(end_amps) != num_tones:
            raise ValueError(f"Number of end_amps ({len(end_amps)}) must match the number of SBGs ({num_tones}).")

        # Set up defaults for optional tuple arguments
        _start_freqs = start_freqs or (None,) * num_tones
        _start_amps = start_amps or (None,) * num_tones
        _phase_resets = phase_resets or (False,) * num_tones

        all_params = []
        from_waveforms_map = {
            wf.sbg_id: wf for wf in from_state.waveforms
        } if isinstance(from_state, RWGActive) else {}

        for i in range(num_tones):
            sbg_id = sbg_ids[i]
            from_wf = from_waveforms_map.get(sbg_id)

            # Infer start points from context if not explicitly provided
            inferred_start_freq = _start_freqs[i] if _start_freqs[i] is not None else (from_wf.freq if from_wf else 0.0)
            inferred_start_amp = _start_amps[i] if _start_amps[i] is not None else (from_wf.amp if from_wf else 0.0)

            # Build waveform for this tone
            freq_slope = (end_freqs[i] - inferred_start_freq) / duration
            amp_slope = (end_amps[i] - inferred_start_amp) / duration

            ramp_params = WaveformParams(
                sbg_id=sbg_id,
                freq_coeffs=(inferred_start_freq, freq_slope),
                amp_coeffs=(inferred_start_amp, amp_slope),
                phase_reset=_phase_resets[i],
            )
            all_params.append(ramp_params)

        play_builder = play(duration=duration, params=tuple(all_params))
        return play_builder(channel, from_state=from_state)

    return MorphismBuilder(single_generator=generator)


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
