import dataclasses
from catseq.core.protocols import State


@dataclasses.dataclass(frozen=True)
class Uninitialized(State):
    pass
