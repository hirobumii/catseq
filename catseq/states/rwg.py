import dataclasses
from typing import Optional, Tuple, ClassVar
import numpy as np
from catseq.protocols import State, Dynamics


@dataclasses.dataclass(frozen=True)
class WaveformParams(Dynamics):
    """
    Encapsulates the complete mathematical description for a DYNAMICAL
    waveform process (e.g., a ramp). This is primarily intended to be held
    by a Morphism in its `dynamics` field.
    """
    
    _ZERO_TOLERANCE: ClassVar[float] = 1e-9
    
    sbg_id: int
    """The ID of the SBG (0-127) these parameters apply to."""

    freq_coeffs: Tuple[Optional[float], ...]
    """Taylor series coefficients (F0-F3) for frequency ramping."""

    amp_coeffs: Tuple[Optional[float], ...]
    """Taylor series coefficients (A0-A3) for amplitude ramping."""

    initial_phase: Optional[float] = 0.0
    
    phase_reset: Optional[bool] = None
    """A flag to indicate if the phase accumulator should be reset."""

    def __post_init__(self):
        # Pad the coefficient tuples to a length of 4 to prevent index errors.
        padded_freq = list(self.freq_coeffs) + [0.0] * (4 - len(self.freq_coeffs))
        object.__setattr__(self, 'freq_coeffs', tuple(padded_freq[:4]))

        padded_amp = list(self.amp_coeffs) + [0.0] * (4 - len(self.amp_coeffs))
        object.__setattr__(self, 'amp_coeffs', tuple(padded_amp[:4]))

    @property
    def required_ramping_order(self) -> int:
        """Returns the minimum ramping order required to execute this waveform."""
        # This property now relies on the __post_init__ to pad the tuples.
        if any(c is not None and not np.isclose(c, 0.0, atol=self._ZERO_TOLERANCE) 
               for c in (self.freq_coeffs[3], self.amp_coeffs[3])):
            return 3
        if any(c is not None and not np.isclose(c, 0.0, atol=self._ZERO_TOLERANCE)
               for c in (self.freq_coeffs[2], self.amp_coeffs[2])):
            return 2
        if any(c is not None and not np.isclose(c, 0.0, atol=self._ZERO_TOLERANCE)
               for c in (self.freq_coeffs[1], self.amp_coeffs[1])):
            return 1
        return 0

    @property
    def is_dynamical(self) -> bool:
        """Convenience property, True if the waveform is dynamic (order > 0)."""
        return self.required_ramping_order > 0


@dataclasses.dataclass(frozen=True)
class StaticWaveform:
    """
    Describes the static, instantaneous parameters of a single SBG.
    This represents a "point in time" and is used within the RWGActive State.
    """
    sbg_id: int
    """The ID of the SBG (0-127)."""

    freq: float
    """Instantaneous frequency in MHz."""

    amp: float
    """Instantaneous amplitude in Full Scale."""

    phase: float
    """Instantaneous phase in radians."""


class RWGState(State):
    """Base class for all states related to the RWG RF channels."""
    pass


@dataclasses.dataclass(frozen=True)
class RWGReady(RWGState):
    """
    State: RF channel is initialized. The carrier is set, but no
    waveform is active.
    """
    carrier_freq: float


@dataclasses.dataclass(frozen=True)
class RWGStaged(RWGState):
    """
    State: Waveform process parameters have been written to staging registers.
    """
    carrier_freq: float


@dataclasses.dataclass(frozen=True)
class RWGArmed(RWGState):
    """
    State: Waveform process parameters are effective (loaded into active
    logic), but the final RF output is off.
    """
    carrier_freq: float
    waveforms: Tuple[StaticWaveform, ...]


@dataclasses.dataclass(frozen=True)
class RWGActive(RWGState):
    """
    State: RF channel is actively outputting a signal. This is a snapshot
    of the instantaneous physical values.
    """
    carrier_freq: float
    waveforms: Tuple[StaticWaveform, ...]
