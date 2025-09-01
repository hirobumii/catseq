"""
Types specific to TTL hardware.
"""
from enum import Enum
from .common import State

class TTLState(State, Enum):
    """TTL 通道状态"""
    UNINITIALIZED = -1
    OFF = 0
    ON = 1
