import dataclasses
from catseq.model import State


@dataclasses.dataclass(frozen=True)
class Uninitialized(State):
    pass