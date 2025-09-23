"""
RWG hardware abstraction layer.

This module provides high-level functions to generate RWG sequences.
These functions return MorphismDefs, which can be composed together
using the >> operator to build complex sequences.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

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


@dataclass
class RWGTarget:
    """Represents a target state for an RWG's sub-band generator (SBG).

    The `sbg_id` is required when setting an initial state, but ignored during a ramp.
    `freq` and `amp` can be set to None during a ramp to indicate no change.
    """
    freq: Optional[float] = None
    amp: Optional[float] = None
    sbg_id: Optional[int] = None


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


def set_state(targets: List[RWGTarget]) -> MorphismDef:
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
            if t.sbg_id is None or t.freq is None or t.amp is None:
                raise ValueError("sbg_id, freq, and amp must be provided for all targets in set_state.")
            params.append(
                WaveformParams(
                    sbg_id=t.sbg_id,
                    freq_coeffs=(t.freq, None, None, None),
                    amp_coeffs=(t.amp, None, None, None),
                    initial_phase=0.0,
                    phase_reset=True,
                )
            )

        load_morphism = rwg_load_coeffs(channel, params, start_state)
        instruction_state = load_morphism.lanes[channel].operations[-1].end_state

        end_waveforms = []
        for t in targets:
            if t.sbg_id is None or t.freq is None or t.amp is None:
                raise ValueError("sbg_id, freq, and amp must be provided for all targets in set_state.")
            end_waveforms.append(
                StaticWaveform(sbg_id=t.sbg_id, freq=t.freq, amp=t.amp, phase=0.0)
            )
        # For set_state, we directly set the snapshot (immediate state change)
        end_state = RWGActive(
            carrier_freq=start_state.carrier_freq, 
            rf_on=getattr(start_state, 'rf_on', False),  # Preserve RF state if available
            snapshot=tuple(end_waveforms),
            pending_waveforms=None
        )

        update_morphism = rwg_update_params(channel, 1e-6, instruction_state, end_state)  # 1us duration

        return load_morphism >> update_morphism

    return MorphismDef(generator)


def linear_ramp(targets: List[Optional[RWGTarget]], duration: float) -> MorphismDef:
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

        # Phase 2: Execute ramp for specified duration (t=0 to t=duration)
        play_ramp_morphism = rwg_update_params(
            channel, duration, ramp_instruction_state, end_state
        )

        # Phase 3: Load static coefficients to stop ramping (t=duration_us, instantaneous)
        load_static_morphism = rwg_load_coeffs(channel, static_params, end_state)
        static_instruction_state = load_static_morphism.lanes[channel].operations[-1].end_state

        # Phase 4: Execute static update to finalize state (t=duration_us, instantaneous)
        stop_ramp_morphism = rwg_update_params(
            channel, 0.0, static_instruction_state, end_state
        )

        # Complete sequence: load_ramp → play_ramp → load_static → stop_ramp
        # Total duration = duration_us (only play_ramp contributes to duration)
        # Static operations execute at t=duration_us, ensuring ramp stops exactly when expected
        return load_ramp_morphism >> play_ramp_morphism >> load_static_morphism >> stop_ramp_morphism

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
