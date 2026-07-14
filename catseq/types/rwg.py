"""Native record and nominal state declarations for RWG source code."""

from __future__ import annotations

from dataclasses import dataclass, field

from .common import State


FloatLike = float
OptionalFloatLike = float | None


@dataclass(frozen=True, slots=True)
class WaveformParams:
    sbg_id: int
    freq_coeffs: tuple[OptionalFloatLike, ...] = (0.0, None, None, None)
    amp_coeffs: tuple[OptionalFloatLike, ...] = (0.0, None, None, None)
    initial_phase: OptionalFloatLike = None
    phase_reset: bool = False
    fct: int | None = None


@dataclass(frozen=True, slots=True)
class StaticWaveform:
    freq: OptionalFloatLike = None
    amp: OptionalFloatLike = None
    sbg_id: int | None = None
    phase: FloatLike = 0.0
    fct: int | None = None


class RWGState(State):
    """Base class for registered RWG states."""


@dataclass(frozen=True, slots=True)
class RWGUninitialized(RWGState):
    pass


@dataclass(frozen=True, slots=True)
class RWGReady(RWGState):
    carrier_freq: FloatLike


@dataclass(frozen=True, slots=True)
class RWGActive(RWGState):
    carrier_freq: FloatLike
    rf_on: bool
    snapshot: tuple[StaticWaveform, ...] = field(default_factory=tuple)
    pending_waveforms: tuple[WaveformParams, ...] | None = None
