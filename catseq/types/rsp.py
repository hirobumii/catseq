from dataclasses import dataclass
from .common import State


class RSPState(State):
    pass


@dataclass(frozen=True)
class RSPUninitialized(RSPState):
    pass


@dataclass(frozen=True)
class RSPWaveformParams:
    rf_out: int # RF0/RF1
    amp: float # 0.0 ~ 1.0
    output_max: float | None = 0.01


@dataclass(frozen=True)
class RSPReady(RSPState):
    carrier_freq: float 
    static_rf: RSPWaveformParams | None = None


@dataclass(frozen=True)
class RSPPIDConfig:
    adc_in: int      # AI0/AI1
    rf_out: int      # RF0/RF1
    dgt_source: int       # DGT Channel Enable 
    setpoint: float       # 0-10 V
    kp: float = -1.0
    ki: float = -0.02
    kd: float = 0.0
    output_max: float | None = 0.01
    # 可继续加：sign, filter, dgt source, ckg source, units


@dataclass(frozen=True)
class RSPPIDReady(RSPState):
    carrier_freq: float 
    config: RSPPIDConfig


@dataclass(frozen=True)
class RSPPIDActive(RSPState):
    carrier_freq: float 
    config: RSPPIDConfig
    hold: bool = False