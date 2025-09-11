"""
Hardware abstraction layer for CatSeq.

This module provides hardware-specific abstractions and utilities
for different types of hardware devices.
"""

from .ttl import pulse, initialize, set_high, set_low, hold

__all__ = [
    'pulse',
    'initialize', 
    'set_high',
    'set_low',
    'hold',
]