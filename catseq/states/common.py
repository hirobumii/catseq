import dataclasses
from catseq.protocols import State


@dataclasses.dataclass(frozen=True)
class Uninitialized(State):
    pass
