"""
CatSeq state definitions module

This module provides all hardware state type definitions including:
- TTL states (TTLOn, TTLOff)
- Common states (Uninitialized)
"""

from .ttl import TTLState, TTLOn, TTLOff
from .common import Uninitialized

__all__ = [
    # TTL states
    "TTLState",
    "TTLOn",
    "TTLOff",

    # Common states
    "Uninitialized",
]