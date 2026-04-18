"""
Types specific to RWG hardware.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

from ..expr import Expr
from .common import State

FloatLike = float | Expr
OptionalFloatLike = float | Expr | None

# --- Dynamic Description ---
@dataclass(frozen=True)
class WaveformParams:
    """
    A description of a dynamic waveform segment using Taylor series coefficients
    for frequency and amplitude.
    """
    sbg_id: int
    freq_coeffs: Tuple[OptionalFloatLike, ...] = (0.0, None, None, None)
    amp_coeffs: Tuple[OptionalFloatLike, ...] = (0.0, None, None, None)
    initial_phase: OptionalFloatLike = None  # Radian
    phase_reset: bool = False
    fct:Optional[int] = None

# --- Static Description ---
@dataclass(frozen=True)
class StaticWaveform:
    """
    An instantaneous snapshot of a single waveform's properties (freq, amp, phase).
    """
    freq: OptionalFloatLike = None  # MHz
    amp: OptionalFloatLike = None  # FS
    sbg_id: Optional[int] = None
    phase: FloatLike = 0.0 # Radian
    fct:Optional[int] = None

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
    carrier_freq: FloatLike

@dataclass(frozen=True)
class RWGActive(RWGState):
    """State where the RWG is actively generating a dynamic waveform."""
    carrier_freq: FloatLike
    rf_on: bool
    snapshot: Tuple[StaticWaveform, ...] = field(default_factory=tuple)
    pending_waveforms: Optional[Tuple[WaveformParams, ...]] = None

    def __post_init__(self):
        # Ensure snapshot is always sorted by SBG ID for consistent comparisons.
        object.__setattr__(
            self, "snapshot", tuple(sorted(self.snapshot, key=lambda wf: wf.sbg_id))
        )
        # Ensure pending_waveforms is also sorted if not None
        if self.pending_waveforms is not None:
            object.__setattr__(
                self, "pending_waveforms", tuple(sorted(self.pending_waveforms, key=lambda wf: wf.sbg_id))
            )

    @property
    def is_active(self) -> bool:
        """The channel is active if any waveform has non-zero amplitude."""
        return any(abs(wf.amp) > 1e-12 for wf in self.snapshot)
