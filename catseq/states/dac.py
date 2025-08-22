import dataclasses
from catseq.protocols import State


class DACState(State):
    pass


@dataclasses.dataclass(frozen=True)
class DACOff(DACState):
    pass

@dataclasses.dataclass(frozen=True)
class DACStatic(DACState):
    voltage: float
