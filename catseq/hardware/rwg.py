"""RWG compiler intrinsics.

This module is the typed Python surface of the RWG source language. The native
frontend recognizes these calls for later target lowering; importing the module
on the host does not construct morphisms or calculate waveforms.
"""

from collections.abc import Sequence

from ..morphism import (
    Morphism,
    atomic_morphism,
    identity,
    morphism,
)
from ..morphism.core import compiler_intrinsic, compiler_only
from ..time_utils import Duration
from ..types.rwg import (
    RWGActive,
    RWGReady,
    RWGUninitialized,
    StaticWaveform,
    WaveformParams,
)


@atomic_morphism("catseq.hardware.rwg.initialize")
def initialize(carrier_freq: float, hard_init: bool = False) -> Morphism:
    """Initialize an RWG channel and configure its carrier."""
    compiler_only("catseq.hardware.rwg.initialize")


@compiler_intrinsic("catseq.hardware.rwg.waveforms")
def _waveforms(
    targets: Sequence[StaticWaveform | None],
    duration: Duration | None = None,
    phase_reset: bool = False,
    ramp_waveforms: Sequence[WaveformParams] | None = None,
) -> list[WaveformParams]:
    """Resolve target descriptions to the waveform parameters consumed by load.

    ``ramp_waveforms`` makes an endpoint's dependency on the preceding ramp
    explicit in source HIR. Later target lowering derives the concrete values.
    """
    compiler_only("catseq.rwg.waveforms")


@atomic_morphism("catseq.hardware.rwg.load")
def load(waveforms: list[WaveformParams]) -> Morphism:
    """Preload waveform parameters for the next RWG play operation."""
    compiler_only("catseq.hardware.rwg.load")


@atomic_morphism("catseq.hardware.rwg.play")
def play() -> Morphism:
    """Apply the coefficients most recently loaded for this RWG channel."""
    compiler_only("catseq.hardware.rwg.play")


@morphism
def set_state(
    targets: list[StaticWaveform], phase_reset: bool = True
) -> Morphism:
    """Load and apply static waveforms on an RWG channel."""
    return load(_waveforms(targets, phase_reset=phase_reset)) >> play()


@morphism
def linear_ramp(
    targets: list[StaticWaveform | None], duration: Duration
) -> Morphism:
    """Ramp active waveforms linearly over ``duration`` seconds.

    The native template keeps the setup, timed region, and endpoint update as
    separate arena nodes. Incoming RWG state is consumed implicitly while
    preparing the two coefficient loads.
    """
    ramp = _waveforms(targets, duration)
    endpoint = _waveforms(targets, ramp_waveforms=ramp)
    return (
        load(ramp)
        >> play()
        >> hold(duration)
        >> load(endpoint)
        >> play()
    )


@atomic_morphism("catseq.hardware.rwg.rf_on")
def rf_on() -> Morphism:
    """Turn the RWG RF switch on."""
    compiler_only("catseq.hardware.rwg.rf_on")


@atomic_morphism("catseq.hardware.rwg.rf_off")
def rf_off() -> Morphism:
    """Turn the RWG RF switch off."""
    compiler_only("catseq.hardware.rwg.rf_off")


@morphism
def rf_pulse(duration: Duration) -> Morphism:
    """Emit an RF pulse lasting ``duration`` seconds."""
    return rf_on() >> hold(duration) >> rf_off()


@compiler_intrinsic("catseq.hardware.rwg.hold")
def hold(duration: Duration) -> Morphism:
    """Move channel-local logical time without changing RWG state."""
    compiler_only("catseq.hardware.rwg.hold")


__all__ = [
    "RWGActive",
    "RWGReady",
    "RWGUninitialized",
    "StaticWaveform",
    "WaveformParams",
    "hold",
    "identity",
    "initialize",
    "linear_ramp",
    "load",
    "play",
    "rf_off",
    "rf_on",
    "rf_pulse",
    "set_state",
]
