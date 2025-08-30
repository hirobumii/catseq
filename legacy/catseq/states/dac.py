from dataclasses import dataclass
from catseq.core.protocols import State


class DACState(State):
    """Base class for DAC channel states"""
    pass


@dataclass(frozen=True)
class DACOff(DACState):
    """DAC channel output disabled"""
    pass


@dataclass(frozen=True)
class DACStatic(DACState):
    """DAC channel outputting static voltage"""
    voltage: float
