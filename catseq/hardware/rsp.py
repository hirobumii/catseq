"""RSP compiler intrinsics.

Only source-language declarations live here.  State validation and hardware
lowering are native compiler passes rather than Python runtime behavior.
"""

from ..morphism import Morphism
from ..morphism.core import compiler_intrinsic, compiler_only
from ..types.rsp import (
    RSPPIDActive,
    RSPPIDConfig,
    RSPPIDReady,
    RSPReady,
    RSPUninitialized,
    RSPWaveformParams,
)


@compiler_intrinsic("catseq.hardware.rsp.initialize")
def initialize(
    carrier_freq: float,
    offset_0: float = 0.0,
    offset_1: float = 0.0,
    flt_typ: str = "rr",
    chn_cpl: str = "dd",
) -> Morphism:
    """Initialize an RSP board and configure its carrier."""
    compiler_only("catseq.hardware.rsp.initialize")


@compiler_intrinsic("catseq.hardware.rsp.pid_config")
def pid_config(
    config: RSPPIDConfig | None = None,
    *,
    ai_channel: int | None = None,
    ao_channel: int | None = None,
    setpoint: float | None = None,
    kp: float = -1.0,
    ki: float = -0.02,
    kd: float = 0.0,
    output_max: float | None = 0.01,
    dgt_source: int | None = None,
) -> Morphism:
    """Configure an RSP PID loop."""
    compiler_only("catseq.hardware.rsp.pid_config")


@compiler_intrinsic("catseq.hardware.rsp.pid_start")
def pid_start() -> Morphism:
    """Start or resume a configured PID loop."""
    compiler_only("catseq.hardware.rsp.pid_start")


@compiler_intrinsic("catseq.hardware.rsp.pid_hold")
def pid_hold() -> Morphism:
    """Hold an active PID loop output."""
    compiler_only("catseq.hardware.rsp.pid_hold")


@compiler_intrinsic("catseq.hardware.rsp.pid_release")
def pid_release() -> Morphism:
    """Release a held PID loop."""
    compiler_only("catseq.hardware.rsp.pid_release")


@compiler_intrinsic("catseq.hardware.rsp.pid_relink")
def pid_relink() -> Morphism:
    """Reconnect a held PID loop."""
    compiler_only("catseq.hardware.rsp.pid_relink")


@compiler_intrinsic("catseq.hardware.rsp.rf_config")
def rf_config(config: RSPWaveformParams) -> Morphism:
    """Configure one static RSP RF output."""
    compiler_only("catseq.hardware.rsp.rf_config")


__all__ = [
    "RSPPIDActive",
    "RSPPIDConfig",
    "RSPPIDReady",
    "RSPReady",
    "RSPUninitialized",
    "RSPWaveformParams",
    "initialize",
    "pid_config",
    "pid_hold",
    "pid_relink",
    "pid_release",
    "pid_start",
    "rf_config",
]
