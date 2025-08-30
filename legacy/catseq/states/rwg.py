from dataclasses import dataclass
from typing import Tuple, Optional
from catseq.core.protocols import State


@dataclass(frozen=True)
class WaveformParams:
    """Taylor coefficients for RWG waveform generation"""
    freq_coeffs: Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]
    amp_coeffs: Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]
    initial_phase: Optional[float] = 0.0


class RWGState(State):
    """Base class for RWG channel states"""
    pass


@dataclass(frozen=True)
class RWGUninitialized(RWGState):
    """RWG channel not yet initialized"""
    pass


@dataclass(frozen=True)
class RWGReady(RWGState):
    """RWG channel initialized with carrier frequency set"""
    carrier_freq: float


@dataclass(frozen=True)
class RWGActive(RWGState):
    """RWG channel actively outputting RF signal"""
    sbg_id: int
    carrier_freq: float
    freq: float
    amp: float
    phase: float
    rf_enabled: bool