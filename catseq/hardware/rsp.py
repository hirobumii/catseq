"""RSP compiler intrinsics.

Only source-language declarations live here.  State validation and hardware
lowering are native compiler passes rather than Python runtime behavior.
"""

from ..morphism import MorphismDef
from ..morphism.core import compiler_only
from ..types.rsp import (
    RSPPIDActive,
    RSPPIDConfig,
    RSPPIDReady,
    RSPReady,
    RSPUninitialized,
    RSPWaveformParams,
)


def initialize(
    carrier_freq: float,
    offset_0: float = 0.0,
    offset_1: float = 0.0,
    flt_typ: str = "rr",
    chn_cpl: str = "dd",
) -> MorphismDef:
    """Initialize an RSP board and configure its carrier."""
    compiler_only("catseq.hardware.rsp.initialize")


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
) -> MorphismDef:
    """Configure an RSP PID loop."""
    compiler_only("catseq.hardware.rsp.pid_config")


def pid_start() -> MorphismDef:
    """Start or resume a configured PID loop."""
    compiler_only("catseq.hardware.rsp.pid_start")


def pid_hold() -> MorphismDef:
    """Hold an active PID loop output."""
    compiler_only("catseq.hardware.rsp.pid_hold")


def pid_release() -> MorphismDef:
    """Release a held PID loop."""
    compiler_only("catseq.hardware.rsp.pid_release")


def rf_config(config: RSPWaveformParams) -> MorphismDef:
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
    "pid_release",
    "pid_start",
    "rf_config",
]
