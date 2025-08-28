"""
CatSeq hardware device definitions
"""

from .base import BaseHardware
from .ttl import TTLDevice

__all__ = [
    "BaseHardware",
    "TTLDevice",
]