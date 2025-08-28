from dataclasses import dataclass
from catseq.core.protocols import State


@dataclass(frozen=True)
class StateA(State):
    pass


@dataclass(frozen=True)
class StateB(State):
    pass


@dataclass(frozen=True)
class StateC(State):
    pass
