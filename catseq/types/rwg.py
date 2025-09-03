"""
Types specific to RWG hardware.
"""
from dataclasses import dataclass, field
from typing import Tuple, Optional, List
from .common import State

# --- Dynamic Description ---
@dataclass(frozen=True)
class WaveformParams:
    """
    A description of a dynamic waveform segment using Taylor series coefficients
    for frequency and amplitude.
    """
    sbg_id: int
    freq_coeffs: Tuple[Optional[float], ...] = (0.0, None, None, None)
    amp_coeffs: Tuple[Optional[float], ...] = (0.0, None, None, None)
    initial_phase: Optional[float] = None  # Radian
    phase_reset: bool = False

# --- Static Description ---
@dataclass(frozen=True)
class StaticWaveform:
    """
    An instantaneous snapshot of a single waveform's properties (freq, amp, phase).
    """
    sbg_id: int
    freq: float  # MHz
    amp: float  # FS
    phase: float  # Radian

# --- Channel States ---
class RWGState(State):
    """Base class for all RWG channel states."""
    pass

@dataclass(frozen=True)
class RWGUninitialized(RWGState):
    """State before the RWG channel has been configured."""
    pass  # No parameters - this is just a marker state

@dataclass(frozen=True)
class RWGReady(RWGState):
    """State after the RWG is configured with a carrier but is not yet outputting."""
    carrier_freq: float
    rf_on: bool = False

@dataclass(frozen=True)
class RWGActive(RWGState):
    """State where the RWG is actively generating a dynamic waveform."""
    carrier_freq: float
    rf_on: bool
    waveforms: Tuple[StaticWaveform, ...] = field(default_factory=tuple)

    def __post_init__(self):
        # Ensure waveforms are always sorted by SBG ID for consistent comparisons.
        object.__setattr__(
            self, "waveforms", tuple(sorted(self.waveforms, key=lambda wf: wf.sbg_id))
        )

    @property
    def is_active(self) -> bool:
        """The channel is active if any waveform has non-zero amplitude."""
        return any(abs(wf.amp) > 1e-12 for wf in self.waveforms)

@dataclass(frozen=True)
class RWGWaveformInstruction(State):
    """Internal state used to pass waveform parameters to the compiler."""
    params: List[WaveformParams]