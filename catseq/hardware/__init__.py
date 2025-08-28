"""
CatSeq hardware device classes

This module provides hardware device implementations with validation capabilities:
- TTLDevice: TTL channel validation
- RWGDevice: RWG channel with Taylor coefficient validation and optional amplitude lock
"""

from .base import BaseHardware
from .ttl import TTLDevice
from .rwg import RWGDevice

__all__ = [
    "BaseHardware",
    "TTLDevice", 
    "RWGDevice",
]