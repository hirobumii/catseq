"""
RWG hardware abstraction layer.

This module provides high-level functions to generate RWG sequences.
These functions return MorphismDefs, which can be composed together
using the >> operator to build complex sequences.
"""

from typing import List, Optional

from ..morphism import Morphism, MorphismDef, from_atomic
from ..atomic import rwg_board_init, rwg_set_carrier, rwg_load_coeffs, rwg_update_params
from ..morphism import identity
from .common import hold
from ..types import (
    Channel,
    State,
    WaveformParams,
    RWGReady,
    RWGActive,
    StaticWaveform,
    RWGUninitialized,
    AtomicMorphism,
    OperationType,
)

from catseq.types.rwg import StaticWaveform


def initialize(carrier_freq: float) -> MorphismDef:
    """Creates a definition for an RWG initialization morphism (composite: board init + carrier set)."""

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, RWGUninitialized):
            if not isinstance(start_state, RWGReady):
                raise TypeError(
                    f"RWG initialize must start from Uninitialized or Ready, got {type(start_state)}"
                )
        # Composite operation: board initialization followed by carrier setting
        return rwg_board_init(channel) >> identity(1e-6) >> rwg_set_carrier(channel, carrier_freq)

    return MorphismDef(generator)


def set_state(targets: List[StaticWaveform],phase_reset=True) -> MorphismDef:
    """
    Creates a definition for a zero-duration ramp (setting an initial state).
    This operation creates a new set of active SBGs and resets their phase.
    """

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, (RWGReady, RWGActive)):
            raise TypeError(
                f"RWG set_state must start from RWGReady or RWGActive, not {type(start_state)}"
            )

        params = []
        for t in targets:
            if t.sbg_id is None:
                raise ValueError("sbg_id must be provided for all targets in set_state.")
            params.append(
                WaveformParams(
                    sbg_id=t.sbg_id,
                    freq_coeffs=(t.freq, None, None, None),
                    amp_coeffs=(t.amp, None, None, None),
                    initial_phase=t.phase,
                    phase_reset=phase_reset,
                )
            )

        load_morphism = rwg_load_coeffs(channel, params, start_state)
        instruction_state = load_morphism.lanes[channel].operations[-1].end_state

        end_waveforms = targets
        # For set_state, we directly set the snapshot (immediate state change)
        end_state = RWGActive(
            carrier_freq=start_state.carrier_freq, 
            rf_on=getattr(start_state, 'rf_on', False),  # Preserve RF state if available
            snapshot=tuple(end_waveforms),
            pending_waveforms=None
        )

        update_morphism = rwg_update_params(channel, instruction_state, end_state)

        return load_morphism >> update_morphism

    return MorphismDef(generator)


def linear_ramp(targets: List[Optional[StaticWaveform]], duration: float) -> MorphismDef:
    """Creates a definition for a linear ramp with phase continuity.

    The ramp will run for exactly the specified duration and then stop at the target values.
    This ensures the total morphism duration matches the user's expectation.

    Timeline:
    - t=0: Load ramp coefficients (instantaneous)
    - t=0 to t=duration: Execute ramp with specified slope
    - t=duration: Load static coefficients to stop ramping (instantaneous)
    - t=duration: Execute static update to finalize target state (instantaneous)

    Args:
        targets: Target values for each RWG parameter (freq, amp, phase)
        duration: Ramp duration in seconds (SI unit)

    Total duration = duration
    """

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, RWGActive):
            raise TypeError(
                "RWG linear_ramp must follow an operation that leaves the channel in an Active state."
            )
        if duration <= 0:
            raise ValueError("Ramp duration must be positive.")

        active_waveforms = start_state.snapshot
        if len(targets) != len(active_waveforms):
            raise ValueError(
                f"The number of targets ({len(targets)}) must match the number of active SBGs ({len(active_waveforms)})."
            )

        # Prepare ramp parameters and static stop parameters
        ramp_params = []
        static_params = []
        end_waveforms = []

        for target, current_wf in zip(targets, active_waveforms):
            sbg_id = current_wf.sbg_id
            start_freq = current_wf.freq
            start_amp = current_wf.amp
            start_phase = current_wf.phase

            # Determine target freq/amp, defaulting to current values if not specified
            target_freq = target.freq if target and target.freq is not None else start_freq
            target_amp = target.amp if target and target.amp is not None else start_amp

            # Calculate ramp rates
            # Convert duration from seconds to microseconds for hardware units
            duration_us = duration * 1e6  # Convert s to us
            freq_ramp_rate = (target_freq - start_freq) / duration_us  # MHz/us
            amp_ramp_rate = (target_amp - start_amp) / duration_us     # units/us

            # Ramp coefficients (for the PLAY phase)
            freq_coeffs = (start_freq, freq_ramp_rate, None, None) if freq_ramp_rate != 0 else (None, None, None, None)
            amp_coeffs = (start_amp, amp_ramp_rate, None, None) if amp_ramp_rate != 0 else (None, None, None, None)

            ramp_params.append(
                WaveformParams(
                    sbg_id=sbg_id,
                    freq_coeffs=freq_coeffs,
                    amp_coeffs=amp_coeffs,
                    initial_phase=start_phase,
                    phase_reset=False, # Ensure phase continuity
                )
            )
            
            # Static coefficients (to stop ramping at t=duration_us)
            static_params.append(
                WaveformParams(
                    sbg_id=sbg_id,
                    freq_coeffs=(target_freq, 0.0, None, None),  # Static at target frequency
                    amp_coeffs=(target_amp, 0.0, None, None),    # Static at target amplitude  
                    initial_phase=0.0,  # Phase will be continuous from ramp
                    phase_reset=False,
                )
            )
            
            end_waveforms.append(
                StaticWaveform(sbg_id=sbg_id, freq=target_freq, amp=target_amp, phase=0.0)
            )

        # Final state after ramp completion
        end_state = RWGActive(
            carrier_freq=start_state.carrier_freq,
            rf_on=start_state.rf_on, # Preserve RF state during ramp
            snapshot=tuple(end_waveforms),
            pending_waveforms=None
        )

        # Phase 1: Load ramp coefficients (t=0, instantaneous)
        load_ramp_morphism = rwg_load_coeffs(channel, ramp_params, start_state)
        ramp_instruction_state = load_ramp_morphism.lanes[channel].operations[-1].end_state

        # Phase 2: Start ramp execution (atomic, 1 cycle)
        start_ramp_morphism = rwg_update_params(
            channel, ramp_instruction_state, ramp_instruction_state
        )

        # Phase 3: Wait for ramp to complete (user-specified duration)
        wait_morphism = identity(duration)

        # Phase 4: Load static coefficients to stop ramping (atomic, 1 cycle)
        load_static_morphism = rwg_load_coeffs(channel, static_params, ramp_instruction_state)
        static_instruction_state = load_static_morphism.lanes[channel].operations[-1].end_state

        # Phase 5: Execute static update to finalize state (atomic, 1 cycle)
        stop_ramp_morphism = rwg_update_params(
            channel, static_instruction_state, end_state
        )

        # Complete sequence: load_ramp → start_ramp → wait → load_static → stop_ramp
        # Total duration = 1 + 1 + duration + 1 + 1 = duration + 4 cycles
        return load_ramp_morphism >> start_ramp_morphism >> wait_morphism >> load_static_morphism >> stop_ramp_morphism

    return MorphismDef(generator)


def cubic_ramp(targets: List[Optional[StaticWaveform]], duration: float, pure_coeffs:List[float]) -> MorphismDef:
    """Creates a definition for a cubic ramp with phase continuity.
    
    This ensures smooth start/stop (zero derivative at endpoints is NOT guaranteed;
    these coefficients are fixed per your specification).

    Args:
        `targets`: Target values for each RWG parameter (freq, amp, phase)

        `duration`: Ramp duration in seconds (SI unit)

        `pure_coeff`: <del>(1-b-c, b, c, 0) for amp(t) = (1-b-c)*t^3 + b*t^2 + c*t</del>
        (d,c,b,a) for amp(t) = a*t^3 + b*t^2 + c*t + d, if the value range is [0,1), a=1-b-c and d=0

    Total morphism duration = duration (plus instantaneous setup/teardown cycles).
    """

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, RWGActive):
            raise TypeError(
                "RWG cubic_ramp must follow an operation that leaves the channel in an Active state."
            )
        if duration <= 0:
            raise ValueError("Ramp duration must be positive.")

        active_waveforms = start_state.snapshot
        if len(targets) != len(active_waveforms):
            raise ValueError(
                f"The number of targets ({len(targets)}) must match the number of active SBGs ({len(active_waveforms)})."
            )

        duration_us = duration * 1e6  # Convert to microseconds for hardware
        if len(pure_coeffs) != 4:
            raise ValueError(
                f"The number of coeffs ({len(pure_coeffs)}) must be 4)."
            )
        d,c,b,a = pure_coeffs
        if d != 0:
            raise ValueError(
                f"The value of 0th order's coefficient must be zero ({d=})."
            )
        # a = 1 - b - c
        ramp_params = []
        static_params = []
        end_waveforms = []

        for target, current_wf in zip(targets, active_waveforms):
            sbg_id = current_wf.sbg_id
            start_freq = current_wf.freq
            start_amp = current_wf.amp
            start_phase = current_wf.phase

            # Determine target values, defaulting to current if not specified
            target_freq = target.freq if target and target.freq is not None else start_freq
            target_amp = target.amp if target and target.amp is not None else start_amp

            duration_us = duration * 1e6
            # --- Frequency: still use linear ramp (or static) ---
            if target_freq != start_freq:
                df = (target_freq-start_freq)
                a_us = a / (duration_us**3) * 6 * df
                b_us = b / (duration_us**2) * 2 * df
                c_us = c / duration_us *df
                d_us = start_amp

                freq_coeffs = (d_us, c, b, a)

                
            else:
                freq_coeffs = (start_freq, None, None, None)

            # --- Amplitude: use cubic polynomial in MICROSECONDS ---
            if target_amp != start_amp:
                # Compute cubic coefficients in SECONDS first
                damp = target_amp - start_amp
                a_us = a / (duration_us**3) * 6 * damp
                b_us = b / (duration_us**2) * 2 * damp
                c_us = c / duration_us * damp
                d_us = start_amp

                print(d_us, c_us, b_us, a_us)

                amp_coeffs = (d_us, c, b, a)  # RWG order: (const, t, t^2, t^3)
            else:
                amp_coeffs = (start_amp, None, None, None)

            ramp_params.append(
                WaveformParams(
                    sbg_id=sbg_id,
                    freq_coeffs=freq_coeffs,
                    amp_coeffs=amp_coeffs,
                    initial_phase=start_phase,
                    phase_reset=False,
                )
            )

            # Static stop state
            static_params.append(
                WaveformParams(
                    sbg_id=sbg_id,
                    freq_coeffs=(target_freq, 0.0, None, None),
                    amp_coeffs=(target_amp, 0.0, 0.0, 0.0),
                    initial_phase=0.0,
                    phase_reset=False,
                )
            )

            end_waveforms.append(
                StaticWaveform(sbg_id=sbg_id, freq=target_freq, amp=target_amp, phase=0.0)
            )

        end_state = RWGActive(
            carrier_freq=start_state.carrier_freq,
            rf_on=start_state.rf_on,
            snapshot=tuple(end_waveforms),
            pending_waveforms=None
        )

        # Build morphism sequence
        load_ramp_morphism = rwg_load_coeffs(channel, ramp_params, start_state)
        ramp_instruction_state = load_ramp_morphism.lanes[channel].operations[-1].end_state

        start_ramp_morphism = rwg_update_params(channel, ramp_instruction_state, ramp_instruction_state)
        wait_morphism = identity(duration)
        load_static_morphism = rwg_load_coeffs(channel, static_params, ramp_instruction_state)
        static_instruction_state = load_static_morphism.lanes[channel].operations[-1].end_state

        stop_ramp_morphism = rwg_update_params(channel, static_instruction_state, end_state)

        return (
            load_ramp_morphism >>
            start_ramp_morphism >>
            wait_morphism >>
            load_static_morphism >>
            stop_ramp_morphism
        )

    return MorphismDef(generator)



from scipy.interpolate import CubicSpline

import numpy as np
def gen_coeff(start, end, n_knots, T, func):

    def get_rtmq_coeffs_from_spline(cs):
        """
        从scipy的CubicSpline对象中提取RTMQv2的泰勒系数。
        """
        segments_data = []
        
        # 比较系数可得：
        # F0 = d, F1 = c, F2 = 2*b, F3 = 6*a
        for i in range(len(cs.x) - 1):
            t_start = cs.x[i]
            t_end = cs.x[i+1]
            duration = t_end - t_start
            
            # 从scipy系数矩阵中提取a, b, c, d
            a = cs.c[0, i]
            b = cs.c[1, i]
            c = cs.c[2, i]
            d = cs.c[3, i]
            
            # 转换为RTMQ的泰勒系数
            F0 = d
            F1 = c
            F2 = 2 * b
            F3 = 6 * a
            
            coeffs = [F0, F1, F2, F3]
            segments_data.append(coeffs)
            
        return segments_data
    
    t_knots = np.linspace(0, T, n_knots)
    y_knots = func(t_knots/T)
    dur = t_knots[1:] - t_knots[:-1]
    coeff = []
    
    # for f0, f1 in zip(starts, ends):
    f0,f1 = start, end
    y = y_knots*(f1-f0)+f0
    # print(t_knots, y/MHZ)
    cs = CubicSpline(t_knots, y, bc_type='natural')
    rtmq_params = get_rtmq_coeffs_from_spline(cs)
    return rtmq_params, dur


def spline_arbi_func_ramp(targets: List[Optional[StaticWaveform]], duration: float, trace, n_knots:int = 11, ) -> MorphismDef:
    """Creates a definition for a cubic ramp with phase continuity.

    This ensures smooth start/stop (zero derivative at endpoints is NOT guaranteed;
    these coefficients are fixed per your specification).

    Args:
        targets: Target values for each RWG parameter (freq, amp, phase)
        duration: Ramp duration in seconds (SI unit)

    Total morphism duration = duration (plus instantaneous setup/teardown cycles).
    """

    def sqrt_blackman(t):
        n = t.shape[0]
        res = np.blackman(2*n-1)[:n]
        res[0] = 0.0
        return np.sqrt(res)

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, RWGActive):
            raise TypeError(
                "RWG cubic_ramp must follow an operation that leaves the channel in an Active state."
            )
        if duration <= 0:
            raise ValueError("Ramp duration must be positive.")

        active_waveforms = start_state.snapshot
        if len(targets) != len(active_waveforms):
            raise ValueError(
                f"The number of targets ({len(targets)}) must match the number of active SBGs ({len(active_waveforms)})."
            )

        duration_us = duration * 1e6  # Convert to microseconds for hardware

        ramp_params = [[] for _ in range(n_knots-1)]
        static_params = []
        end_waveforms = []

        for target, current_wf in zip(targets, active_waveforms):
            sbg_id = current_wf.sbg_id
            start_freq = current_wf.freq
            start_amp = current_wf.amp
            start_phase = current_wf.phase

            # Determine target values, defaulting to current if not specified
            target_freq = target.freq if target and target.freq is not None else start_freq
            target_amp = target.amp if target and target.amp is not None else start_amp

            duration_us = duration * 1e6
            # --- Frequency: still use linear ramp (or static) ---
            if target_freq != start_freq:
                freq_coeffs, durs_us = gen_coeff(start_freq, target_freq, n_knots, duration_us, trace)
            else:
                freq_coeffs = [(start_freq, 0.0, 0.0, 0.0)]* (n_knots-1)

            # --- Amplitude: use cubic polynomial in MICROSECONDS ---
            if target_amp != start_amp:
                # Compute cubic coefficients in SECONDS first
                amp_coeffs, durs_us = gen_coeff(start_amp, target_amp, n_knots, duration_us, trace)
            else:
                amp_coeffs = [(start_amp, 0.0, 0.0, 0.0)] * (n_knots-1)
        
            for i, (freq_coeff, amp_coeff, dur) in enumerate(zip(freq_coeffs, amp_coeffs, durs_us)):
                ramp_params[i].append(
                    WaveformParams(
                        sbg_id=sbg_id,
                        freq_coeffs=freq_coeff,
                        amp_coeffs=amp_coeff,
                        initial_phase=start_phase,
                        phase_reset=False,
                    )
                )

            # Static stop state
            static_params.append(
                WaveformParams(
                    sbg_id=sbg_id,
                    freq_coeffs=(target_freq, 0.0, 0.0, 0.0),
                    amp_coeffs=(target_amp, 0.0, 0.0, 0.0),
                    initial_phase=0.0,
                    phase_reset=False,
                )
            )

            end_waveforms.append(
                StaticWaveform(sbg_id=sbg_id, freq=target_freq, amp=target_amp, phase=0.0)
            )

        end_state = RWGActive(
            carrier_freq=start_state.carrier_freq,
            rf_on=start_state.rf_on,
            snapshot=tuple(end_waveforms),
            pending_waveforms=None
        )
        
        load_ramp_morphism = rwg_load_coeffs(channel, ramp_params[0], start_state)
        ramp_instruction_state = load_ramp_morphism.lanes[channel].operations[-1].end_state
        start_ramp_morphism = rwg_update_params(channel, ramp_instruction_state, ramp_instruction_state)
        wait_morphism = identity(durs_us[0]/1e6)
        morphism = (
            load_ramp_morphism
            >>start_ramp_morphism
            >>wait_morphism
        )
        for i_stage  in range(1,len(ramp_params)):
            # Build morphism sequence
            load_ramp_morphism = rwg_load_coeffs(channel, ramp_params[i_stage], start_state)
            ramp_instruction_state = load_ramp_morphism.lanes[channel].operations[-1].end_state

            start_ramp_morphism = rwg_update_params(channel, ramp_instruction_state, ramp_instruction_state)
            wait_morphism = identity(durs_us[i_stage]/1e6)
            morphism = (
                morphism
                >>  load_ramp_morphism
                >>  start_ramp_morphism
                >>  wait_morphism
            )

        load_static_morphism = rwg_load_coeffs(channel, static_params, ramp_instruction_state)
        static_instruction_state = load_static_morphism.lanes[channel].operations[-1].end_state

        stop_ramp_morphism = rwg_update_params(channel, static_instruction_state, end_state)

        return (
            morphism >>
            load_static_morphism >>
            stop_ramp_morphism
        )

    return MorphismDef(generator)






# hold function is now imported from .common


def _create_rf_switch_morphism(on: bool) -> MorphismDef:
    """Helper function to create MorphismDefs for RF switch control."""

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, (RWGReady, RWGActive)):
            raise TypeError(f"RF switch control must start from RWGReady or RWGActive, not {type(start_state)}")

        # Reconstruct the end state with the toggled rf_on flag
        if isinstance(start_state, RWGReady):
            end_state = RWGReady(carrier_freq=start_state.carrier_freq)  # RWGReady no longer has rf_on
        else: # RWGActive
            end_state = RWGActive(
                carrier_freq=start_state.carrier_freq,
                rf_on=on,
                snapshot=start_state.snapshot,
                pending_waveforms=start_state.pending_waveforms
            )

        # Create the atomic operation for the switch
        # Assume it takes 1 cycle to execute
        op = AtomicMorphism(
            channel=channel,
            start_state=start_state,
            end_state=end_state,
            duration_cycles=1,
            operation_type=OperationType.RWG_RF_SWITCH,
        )
        return from_atomic(op)

    return MorphismDef(generator)


def rf_on() -> MorphismDef:
    """Creates a definition to turn the RF switch on."""
    return _create_rf_switch_morphism(on=True)


def rf_off() -> MorphismDef:
    """Creates a definition to turn the RF switch off."""
    return _create_rf_switch_morphism(on=False)


def rf_pulse(duration: float) -> MorphismDef:
    """Creates a definition for an RF pulse: rf_on → wait → rf_off.
    
    This is a composite operation that temporarily turns on the RF switch
    for the specified duration, then turns it off. The operation appears
    externally as RWGActive(rf_on=False) → RWGActive(rf_on=False).
    
    Args:
        duration: Duration of the RF pulse in seconds (SI unit)
        
    Returns:
        MorphismDef that generates the RF pulse sequence
    """
    
    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, RWGActive):
            raise TypeError(f"RF pulse requires RWGActive state, got {type(start_state)}")
        if start_state.rf_on:
            raise ValueError("RF pulse requires rf_on=False as starting state")
        
        # Create the component operations
        rf_on_def = rf_on()
        rf_off_def = rf_off()
        
        # Generate rf_on operation
        rf_on_morphism = rf_on_def(channel, start_state)
        
        # Calculate intermediate state after rf_on
        intermediate_state = RWGActive(
            carrier_freq=start_state.carrier_freq,
            rf_on=True,
            snapshot=start_state.snapshot,
            pending_waveforms=start_state.pending_waveforms
        )
        
        # Create wait operation with user's specified duration
        wait_morphism = identity(duration)
        
        # Generate rf_off operation  
        rf_off_morphism = rf_off_def(channel, intermediate_state)
        
        # Compose the sequence: rf_on → wait → rf_off
        return rf_on_morphism >> wait_morphism >> rf_off_morphism
        
    return MorphismDef(generator)
