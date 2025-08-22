import dataclasses
from catseq.protocols import State


class TTLState(State):
    pass

@dataclasses.dataclass(frozen=True)
class TTLInput(TTLState):
    pass

@dataclasses.dataclass(frozen=True)
class TTLOutputOn(TTLState):
    pass

@dataclasses.dataclass(frozen=True)
class TTLOutputOff(TTLState):
    pass
