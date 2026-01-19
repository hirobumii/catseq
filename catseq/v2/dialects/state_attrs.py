"""Structured state attributes for CatSeq V2 dialects.

This module defines type-safe ParametrizedAttribute classes for representing
hardware states, replacing the unsafe DictionaryAttr approach.

All types are based on v1 system analysis:
- TTLState → TTLStateAttr
- StaticWaveform → StaticWaveformAttr (with Optional fields)
- WaveformParams → WaveformParamsAttr (with Optional coefficients)
- RWGActive → RWGStateAttr
- RSPState → RSPStateAttr (new in v2)

IMPORTANT: Optional values use special sentinel values:
- Float: NaN represents None (no change to register)
- Int: -1 represents None (no change to register)
"""

import math
from xdsl.irdl import irdl_attr_definition, ParametrizedAttribute, param_def
from xdsl.dialects.builtin import (
    IntegerAttr,
    FloatAttr,
    ArrayAttr,
    BoolAttr,
    NoneAttr,
    IntegerType,
    Float64Type,
)


# =============================================================================
# TTL State Attributes
# =============================================================================


@irdl_attr_definition
class TTLStateAttr(ParametrizedAttribute):
    """TTL channel state.

    Corresponds to v1: catseq.types.ttl.TTLState

    Values:
    - 0: OFF
    - 1: ON
    - -1: UNINITIALIZED
    """

    name = "catseq.ttl_state"

    value: IntegerAttr = param_def(IntegerAttr)

    @staticmethod
    def off():
        """Create OFF state (value = 0)."""
        return TTLStateAttr([IntegerAttr(0, IntegerType(8))])

    @staticmethod
    def on():
        """Create ON state (value = 1)."""
        return TTLStateAttr([IntegerAttr(1, IntegerType(8))])

    @staticmethod
    def uninitialized():
        """Create UNINITIALIZED state (value = -1)."""
        return TTLStateAttr([IntegerAttr(-1, IntegerType(8))])

    def get_value(self) -> int:
        """Get the state value."""
        return self.value.value.data

    def is_on(self) -> bool:
        """Check if state is ON."""
        return self.get_value() == 1

    def is_off(self) -> bool:
        """Check if state is OFF."""
        return self.get_value() == 0


# =============================================================================
# RWG Waveform Attributes
# =============================================================================


@irdl_attr_definition
class StaticWaveformAttr(ParametrizedAttribute):
    """Static waveform snapshot.

    Corresponds to v1: catseq.types.rwg.StaticWaveform

    Units:
    - freq: MHz (NaN = None, no change to register)
    - amp: Full Scale [-1, 1] (NaN = None, no change to register)
    - sbg_id: Signal Bus Generator ID (-1 = None, no change to register)
    - phase: Radians (always specified, default 0.0)

    IMPORTANT: NaN and -1 represent None - do not change the corresponding register.
    """

    name = "catseq.static_waveform"

    sbg_id: IntegerAttr = param_def(IntegerAttr)
    freq: FloatAttr | NoneAttr = param_def(FloatAttr | NoneAttr)
    amp: FloatAttr | NoneAttr = param_def(FloatAttr | NoneAttr)
    phase: FloatAttr | NoneAttr = param_def(FloatAttr | NoneAttr)

    @staticmethod
    def create(
        sbg_id: int,
        freq: float | None,
        amp: float | None,
        phase: float = 0.0,
    ):
        """Create a static waveform snapshot."""

        def to_attr(val: float | None) -> FloatAttr | NoneAttr:
            if val is None:
                return NoneAttr()
            return FloatAttr(val, Float64Type())

        return StaticWaveformAttr([
            IntegerAttr(sbg_id, IntegerType(32)),
            to_attr(freq),
            to_attr(amp),
            FloatAttr(phase, Float64Type()),
        ])
    
    def get_sbg_id(self) -> int:
        """Get Signal Bus Generator ID."""
        return self.sbg_id.value.data

    def get_freq(self) -> float | None:
        """Get frequency in MHz (None = no change to register)."""
        if isinstance(self.freq, NoneAttr):
            return None
        return self.freq.value.data
    
    def get_amp(self) -> float | None:
        """Get amplitude in Full Scale (None = no change to register)."""
        if isinstance(self.amp, NoneAttr):
            return None
        return self.amp.value.data

    def get_phase(self) -> float:
        """Get phase in Radians."""
        return self.phase.value.data

    def is_active(self) -> bool:
        """Check if waveform is active (amplitude > threshold).

        Returns False if amplitude is None (no change).
        """
        amp = self.get_amp()
        if amp is None:
            return False
        return abs(amp) > 1e-12


@irdl_attr_definition
class WaveformParamsAttr(ParametrizedAttribute):
    """Dynamic waveform parameters using Taylor expansion.

    Corresponds to v1: catseq.types.rwg.WaveformParams

    Frequency and amplitude use Taylor expansion:
    f(t) = f0 + f1*t + f2*t^2 + f3*t^3
    a(t) = a0 + a1*t + a2*t^2 + a3*t^3

    Units:
    - freq_c0: MHz (base frequency)
    - freq_c1-c3: MHz/μs^n (higher-order coefficients, NaN = None)
    - amp_c0: FS (base amplitude)
    - amp_c1-c3: FS/μs^n (higher-order coefficients, NaN = None)

    IMPORTANT: NaN represents None for optional coefficients.
    """

    name = "catseq.waveform_params"

    sbg_id: IntegerAttr = param_def(IntegerAttr)

    # Frequency Taylor coefficients [f0, f1, f2, f3]
    freq_c0: FloatAttr | NoneAttr = param_def(FloatAttr | NoneAttr)
    freq_c1: FloatAttr | NoneAttr = param_def(FloatAttr | NoneAttr)
    freq_c2: FloatAttr | NoneAttr = param_def(FloatAttr | NoneAttr)
    freq_c3: FloatAttr | NoneAttr = param_def(FloatAttr | NoneAttr)

    # Amplitude Taylor coefficients [a0, a1, a2, a3]
    amp_c0: FloatAttr | NoneAttr = param_def(FloatAttr | NoneAttr)
    amp_c1: FloatAttr | NoneAttr = param_def(FloatAttr | NoneAttr)
    amp_c2: FloatAttr | NoneAttr = param_def(FloatAttr | NoneAttr)
    amp_c3: FloatAttr | NoneAttr = param_def(FloatAttr | NoneAttr)

    initial_phase: FloatAttr | NoneAttr = param_def(FloatAttr | NoneAttr)
    phase_reset: BoolAttr = param_def(BoolAttr)

    @staticmethod
    def create(
        sbg_id: int,
        freq_c0: float | None = None,
        freq_c1: float | None = None,
        freq_c2: float | None = None,
        freq_c3: float | None = None,
        amp_c0: float | None = None,
        amp_c1: float | None = None,
        amp_c2: float | None = None,
        amp_c3: float | None = None,
        initial_phase: float | None = None,
        phase_reset: bool = False,
    ):
        """Create waveform parameters with Taylor coefficients.

        Args:
            sbg_id: Signal Bus Generator ID
            freq_c0: Base frequency (MHz, default 0.0)
            freq_c1: Linear frequency ramp rate (MHz/μs, None = not used)
            freq_c2: Quadratic frequency coefficient (None = not used)
            freq_c3: Cubic frequency coefficient (None = not used)
            amp_c0: Base amplitude (FS, default 0.0)
            amp_c1: Linear amplitude ramp rate (FS/μs, None = not used)
            amp_c2: Quadratic amplitude coefficient (None = not used)
            amp_c3: Cubic amplitude coefficient (None = not used)
            initial_phase: Starting phase (Radians, None = not specified)
            phase_reset: Reset phase on load
        """
        float_type = Float64Type()

        def to_attr(val: float | None) -> FloatAttr | NoneAttr:
            if val is None:
                return NoneAttr()
            return FloatAttr(val, float_type)

        return WaveformParamsAttr([
            IntegerAttr(sbg_id, IntegerType(32)),
            to_attr(freq_c0),
            to_attr(freq_c1),
            to_attr(freq_c2),
            to_attr(freq_c3),
            to_attr(amp_c0),
            to_attr(amp_c1),
            to_attr(amp_c2),
            to_attr(amp_c3),
            to_attr(initial_phase),
            BoolAttr(phase_reset),
        ])

    def get_sbg_id(self) -> int:
        """Get Signal Bus Generator ID."""
        return self.sbg_id.value.data

    def get_freq_coeffs(self) -> tuple[float | None, float | None, float | None, float | None]:
        """Get frequency Taylor coefficients [f0, f1, f2, f3].

        Returns:
            Tuple with f0-f3 (float or None)
        """
        def from_attr(attr: FloatAttr | NoneAttr) -> float | None:
            return None if isinstance(attr, NoneAttr) else attr.value.data

        return (
            from_attr(self.freq_c0),
            from_attr(self.freq_c1),
            from_attr(self.freq_c2),
            from_attr(self.freq_c3),
        )

    def get_amp_coeffs(self) -> tuple[float | None, float | None, float | None, float | None]:
        """Get amplitude Taylor coefficients [a0, a1, a2, a3].

        Returns:
            Tuple with a0-a3 (float or None)
        """
        def from_attr(attr: FloatAttr | NoneAttr) -> float | None:
            return None if isinstance(attr, NoneAttr) else attr.value.data

        return (
            from_attr(self.amp_c0),
            from_attr(self.amp_c1),
            from_attr(self.amp_c2),
            from_attr(self.amp_c3),
        )

    def get_initial_phase(self) -> float | None:
        """Get initial phase in Radians (None = not specified)."""
        return None if isinstance(self.initial_phase, NoneAttr) else self.initial_phase.value.data

    def get_phase_reset(self) -> bool:
        """Check if phase reset is enabled."""
        return self.phase_reset.value.data


@irdl_attr_definition
class RWGStateAttr(ParametrizedAttribute):
    """RWG channel state.

    Corresponds to v1: catseq.types.rwg.RWGActive

    Contains current snapshot and pending waveforms.
    Snapshots and pending waveforms are automatically sorted by sbg_id.
    """

    name = "catseq.rwg_state"

    carrier_freq: FloatAttr = param_def(FloatAttr)
    rf_on: BoolAttr = param_def(BoolAttr)

    # ArrayAttr of StaticWaveformAttr (sorted by sbg_id)
    snapshot: ArrayAttr = param_def(ArrayAttr)

    # ArrayAttr of WaveformParamsAttr (sorted by sbg_id)
    pending_waveforms: ArrayAttr = param_def(ArrayAttr)

    @staticmethod
    def create(
        carrier_freq: float,
        rf_on: bool,
        snapshot: list[StaticWaveformAttr],
        pending_waveforms: list[WaveformParamsAttr],
    ):
        """Create RWG state.

        Args:
            carrier_freq: Carrier frequency in MHz
            rf_on: RF switch state
            snapshot: List of current waveform snapshots
            pending_waveforms: List of pending waveforms

        Note: Lists are automatically sorted by sbg_id for consistency.
        """
        # Sort by sbg_id (matching v1 behavior)
        sorted_snapshot = sorted(
            snapshot,
            key=lambda wf: wf.get_sbg_id()
        )
        sorted_pending = sorted(
            pending_waveforms,
            key=lambda wf: wf.get_sbg_id()
        )

        return RWGStateAttr([
            FloatAttr(carrier_freq, Float64Type()),
            BoolAttr(rf_on),
            ArrayAttr(sorted_snapshot),
            ArrayAttr(sorted_pending),
        ])

    def get_carrier_freq(self) -> float:
        """Get carrier frequency in MHz."""
        return self.carrier_freq.value.data

    def get_rf_on(self) -> bool:
        """Check if RF is on."""
        return self.rf_on.value.data

    def get_snapshot(self) -> list[StaticWaveformAttr]:
        """Get current waveform snapshots (sorted by sbg_id)."""
        return list(self.snapshot.data)

    def get_pending_waveforms(self) -> list[WaveformParamsAttr]:
        """Get pending waveforms (sorted by sbg_id)."""
        return list(self.pending_waveforms.data)

    def is_active(self) -> bool:
        """Check if any waveform is active (amplitude > threshold)."""
        for wf in self.get_snapshot():
            amp = wf.get_amp()
            if amp is not None and abs(amp) > 1e-12:
                return True
        return False


# =============================================================================
# RSP State Attributes (v2 new feature)
# =============================================================================


@irdl_attr_definition
class RSPStateAttr(ParametrizedAttribute):
    """RSP (signal processing) channel state.

    New feature in v2, not present in v1 system.
    """

    name = "catseq.rsp_state"

    threshold: FloatAttr = param_def(FloatAttr)
    gain: FloatAttr = param_def(FloatAttr)
    integration_time: IntegerAttr = param_def(IntegerAttr)

    @staticmethod
    def create(threshold: float, gain: float, integration_time: int):
        """Create RSP state.

        Args:
            threshold: Detection threshold
            gain: Signal gain
            integration_time: Integration time in cycles
        """
        return RSPStateAttr([
            FloatAttr(threshold, Float64Type()),
            FloatAttr(gain, Float64Type()),
            IntegerAttr(integration_time, IntegerType(32)),
        ])

    def get_threshold(self) -> float:
        """Get detection threshold."""
        return self.threshold.value.data

    def get_gain(self) -> float:
        """Get signal gain."""
        return self.gain.value.data

    def get_integration_time(self) -> int:
        """Get integration time in cycles."""
        return self.integration_time.value.data
