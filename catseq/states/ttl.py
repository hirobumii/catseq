from dataclasses import dataclass
from catseq.core.protocols import State


class TTLState(State):
    """Base class for TTL channel states"""
    pass


@dataclass(frozen=True)
class TTLInput(TTLState):
    """TTL channel configured as input"""
    pass


@dataclass(frozen=True)
class TTLOn(TTLState):
    """TTL channel outputting high signal"""
    pass


@dataclass(frozen=True)
class TTLOff(TTLState):
    """TTL channel outputting low signal"""
    pass
