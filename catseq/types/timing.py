"""
Timing system with epoch-based logical timestamps for distributed synchronization.

This module implements the (epoch, time_offset) compound timestamp design discussed earlier.
"""

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class LogicalTimestamp:
    """
    A compound timestamp with epoch and time offset.
    
    epoch: A monotonically increasing integer that increments after each global sync.
           Represents different time reference frames.
    time_offset_cycles: Time elapsed since the beginning of this epoch, in clock cycles.
    
    The key insight is that timestamps from different epochs cannot be directly compared
    or used in arithmetic operations - they belong to different time reference systems.
    """
    epoch: int
    time_offset_cycles: int
    
    def __post_init__(self):
        if self.epoch < 0:
            raise ValueError(f"Epoch must be non-negative, got {self.epoch}")
        if self.time_offset_cycles < 0:
            raise ValueError(f"Time offset must be non-negative, got {self.time_offset_cycles}")
    
    def __lt__(self, other: "LogicalTimestamp") -> bool:
        """Compare timestamps only within the same epoch."""
        if not isinstance(other, LogicalTimestamp):
            return NotImplemented
        if self.epoch != other.epoch:
            raise ValueError(
                f"Cannot compare timestamps from different epochs: "
                f"epoch {self.epoch} vs epoch {other.epoch}. "
                f"Timestamps from different epochs belong to different time reference systems."
            )
        return self.time_offset_cycles < other.time_offset_cycles
    
    def __sub__(self, other: "LogicalTimestamp") -> int:
        """Calculate time difference only within the same epoch."""
        if not isinstance(other, LogicalTimestamp):
            return NotImplemented
        if self.epoch != other.epoch:
            raise ValueError(
                f"Cannot subtract timestamps from different epochs: "
                f"epoch {self.epoch} vs epoch {other.epoch}. "
                f"Time arithmetic across epochs is meaningless."
            )
        return self.time_offset_cycles - other.time_offset_cycles
    
    def __add__(self, cycles: int) -> "LogicalTimestamp":
        """Add time within the same epoch."""
        if not isinstance(cycles, int):
            return NotImplemented
        if cycles < 0:
            raise ValueError(f"Cannot add negative time: {cycles}")
        return LogicalTimestamp(self.epoch, self.time_offset_cycles + cycles)
    
    @property
    def time_offset_us(self) -> float:
        """Convert time offset to microseconds (250MHz clock)."""
        return self.time_offset_cycles / 250.0
    
    @classmethod
    def at_epoch_start(cls, epoch: int) -> "LogicalTimestamp":
        """Create a timestamp at the beginning of an epoch."""
        return cls(epoch, 0)
    
    @classmethod 
    def from_cycles(cls, epoch: int, cycles: int) -> "LogicalTimestamp":
        """Create a timestamp from epoch and cycles."""
        return cls(epoch, cycles)
    
    def __str__(self) -> str:
        return f"({self.epoch}, {self.time_offset_us:.1f}μs)"
    
    def __repr__(self) -> str:
        return f"LogicalTimestamp(epoch={self.epoch}, time_offset_cycles={self.time_offset_cycles})"


# Type alias for backward compatibility during migration
TimestampType = Union[int, LogicalTimestamp]


def is_same_epoch(ts1: LogicalTimestamp, ts2: LogicalTimestamp) -> bool:
    """Check if two timestamps belong to the same epoch."""
    return ts1.epoch == ts2.epoch


def increment_epoch(current_epoch: int) -> int:
    """Get the next epoch number."""
    return current_epoch + 1