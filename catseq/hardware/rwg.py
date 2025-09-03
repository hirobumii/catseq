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
class InitialTarget:
    """Defines the initial state for a single SBG, requiring an explicit ID."""
    sbg_id: int
    freq: float
    amp: float

@dataclass
class RampTarget:
    """Defines the ramp destination for a single, already-active SBG."""
    target_freq: float
    target_amp: float


def initialize(carrier_freq: float) -> MorphismDef:
    """Creates a definition for an RWG initialization morphism (composite: board init + carrier set)."""

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, RWGUninitialized):
            if not isinstance(start_state, RWGReady):
                raise TypeError(
                    f"RWG initialize must start from Uninitialized or Ready, got {type(start_state)}"
                )
        # Composite operation: board initialization followed by carrier setting
        return rwg_board_init(channel) >> rwg_set_carrier(channel, carrier_freq)

    return MorphismDef(generator)


def set_state(targets: List[InitialTarget]) -> MorphismDef:
    """
    Creates a definition for a zero-duration ramp (setting an initial state).
    This operation creates a new set of active SBGs and resets their phase.
    """

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, (RWGReady, RWGActive)):
            raise TypeError(
                f"RWG set_state must start from RWGReady or RWGActive, not {type(start_state)}"
            )

        params = [
            WaveformParams(
                sbg_id=t.sbg_id,
                freq_coeffs=(t.freq, None, None, None),
                amp_coeffs=(t.amp, None, None, None),
                initial_phase=0.0,
                phase_reset=True,
            )
            for t in targets
        ]

        load_morphism = rwg_load_coeffs(channel, params, start_state)
        instruction_state = load_morphism.lanes[channel].operations[-1].end_state

        end_waveforms = [
            StaticWaveform(sbg_id=t.sbg_id, freq=t.freq, amp=t.amp, phase=0.0)
            for t in targets
        ]
        rf_should_be_on = any(abs(t.amp) > 1e-9 for t in targets)
        end_state = RWGActive(
            carrier_freq=start_state.carrier_freq, rf_on=rf_should_be_on, waveforms=tuple(end_waveforms)
        )

        update_morphism = rwg_update_params(channel, 0.0, instruction_state, end_state)

        return load_morphism >> update_morphism

    return MorphismDef(generator)


def linear_ramp(targets: List[Optional[RampTarget]], duration_us: float) -> MorphismDef:
    """Creates a definition for a linear ramp with phase continuity."""

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, RWGActive):
            raise TypeError(
                "RWG linear_ramp must follow an operation that leaves the channel in an Active state."
            )
        if duration_us <= 0:
            raise ValueError("Ramp duration must be positive.")

        active_waveforms = start_state.waveforms
        if len(targets) != len(active_waveforms):
            raise ValueError(
                f"The number of targets ({len(targets)}) must match the number of active SBGs ({len(active_waveforms)})."
            )

        params = []
        end_waveforms = []

        for target, current_wf in zip(targets, active_waveforms):
            sbg_id = current_wf.sbg_id
            start_freq = current_wf.freq
            start_amp = current_wf.amp
            start_phase = current_wf.phase

            if target is None:
                target_freq = start_freq
                target_amp = start_amp
            else:
                target_freq = target.target_freq
                target_amp = target.target_amp

            freq_ramp_rate = (target_freq - start_freq) / duration_us
            amp_ramp_rate = (target_amp - start_amp) / duration_us

            params.append(
                WaveformParams(
                    sbg_id=sbg_id,
                    freq_coeffs=(start_freq, freq_ramp_rate, None, None),
                    amp_coeffs=(start_amp, amp_ramp_rate, None, None),
                    initial_phase=start_phase,
                    phase_reset=False, # Ensure phase continuity
                )
            )
            end_waveforms.append(
                StaticWaveform(sbg_id=sbg_id, freq=target_freq, amp=target_amp, phase=0.0)
            )

        load_morphism = rwg_load_coeffs(channel, params, start_state)
        instruction_state = load_morphism.lanes[channel].operations[-1].end_state

        end_state = RWGActive(
            carrier_freq=start_state.carrier_freq,
            rf_on=start_state.rf_on, # Preserve RF state during ramp
            waveforms=tuple(end_waveforms)
        )

        update_morphism = rwg_update_params(
            channel, duration_us, instruction_state, end_state
        )

        return load_morphism >> update_morphism

    return MorphismDef(generator)


def hold(duration_us: float) -> MorphismDef:
    """Creates a definition for a hold (wait) operation."""

    def generator(channel: Channel, start_state: State) -> Morphism:
        return identity(duration_us)

    return MorphismDef(generator)


def _create_rf_switch_morphism(on: bool) -> MorphismDef:
    """Helper function to create MorphismDefs for RF switch control."""

    def generator(channel: Channel, start_state: State) -> Morphism:
        if not isinstance(start_state, (RWGReady, RWGActive)):
            raise TypeError(f"RF switch control must start from RWGReady or RWGActive, not {type(start_state)}")

        if start_state.rf_on == on:
            # If the state is already correct, do nothing (return identity)
            return identity(0)

        # Reconstruct the end state with the toggled rf_on flag
        if isinstance(start_state, RWGReady):
            end_state = RWGReady(carrier_freq=start_state.carrier_freq, rf_on=on)
        else: # RWGActive
            end_state = RWGActive(
                carrier_freq=start_state.carrier_freq,
                rf_on=on,
                waveforms=start_state.waveforms
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
