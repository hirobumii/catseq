"""
Core types and data structures for CatSeq framework.

This module contains the fundamental types that form the foundation of the CatSeq
framework, including Board, Channel, and state enumerations.
"""

from dataclasses import dataclass
from enum import Enum, auto


@dataclass(frozen=True)
class Board:
    """板卡标识符"""
    id: str  # 板卡ID，如 "RWG_0", "RWG_1"
    
    def __str__(self):
        return self.id


@dataclass(frozen=True) 
class Channel:
    """TTL 通道标识符"""
    board: Board      # 所属板卡
    local_id: int     # 板卡内的通道号 (0-based)
    
    def __post_init__(self):
        if self.local_id < 0:
            raise ValueError(f"Channel local_id must be non-negative, got {self.local_id}")
    
    @property
    def global_id(self) -> str:
        """全局通道标识符"""
        return f"{self.board.id}_TTL_{self.local_id}"
    
    def __str__(self):
        return self.global_id


class TTLState(Enum):
    """TTL 通道状态"""
    UNINITIALIZED = -1  # 未初始化状态
    OFF = 0             # 低电平
    ON = 1              # 高电平


class OperationType(Enum):
    """原子操作类型"""
    # TTL 操作
    TTL_INIT = auto()   # TTL 初始化：UNINITIALIZED → OFF
    TTL_ON = auto()     # TTL 开启：OFF → ON  
    TTL_OFF = auto()    # TTL 关闭：ON → OFF
    
    # 时间操作
    WAIT = auto()       # 等待：保持当前状态