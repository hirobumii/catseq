"""
Lane and physical operation management.

This module handles the physical representation of operations, including Lane
objects that group operations by channel and PhysicalLane objects that merge
operations across multiple channels for hardware execution.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .types import Board, Channel, TTLState, OperationType
from .atomic import AtomicMorphism
from .time_utils import cycles_to_us


@dataclass(frozen=True)
class Lane:
    """通道 Lane - 单个通道的操作序列"""
    operations: Tuple[AtomicMorphism, ...]  # 操作序列
    
    @property
    def total_duration_cycles(self) -> int:
        """总时长（时钟周期）"""
        return sum(op.duration_cycles for op in self.operations)
    
    @property
    def total_duration_us(self) -> float:
        """总时长（微秒）"""
        return cycles_to_us(self.total_duration_cycles)
    
    def __str__(self):
        if len(self.operations) == 1:
            return str(self.operations[0])
        else:
            return f"{len(self.operations)}ops"


@dataclass(frozen=True)
class PhysicalOperation:
    """物理操作 - 带时间戳的原子操作"""
    operation: AtomicMorphism
    timestamp_cycles: int  # 操作开始时间（时钟周期）
    
    @property
    def timestamp_us(self) -> float:
        """操作开始时间（微秒）"""
        return cycles_to_us(self.timestamp_cycles)


@dataclass(frozen=True)
class PhysicalLane:
    """物理 Lane - 单个板卡的所有操作，按时间排序"""
    board: Board
    operations: Tuple[PhysicalOperation, ...]
    
    def __str__(self):
        total_cycles = max(
            (op.timestamp_cycles + op.operation.duration_cycles for op in self.operations),
            default=0
        )
        total_us = cycles_to_us(total_cycles)
        return f"⚡ {self.board.id}[{len(self.operations)}ops] ({total_us:.1f}μs)"


def merge_board_lanes(board: Board, board_lanes: Dict[Channel, Lane]) -> PhysicalLane:
    """将同一板卡的多个通道 Lane 合并为 PhysicalLane
    
    Args:
        board: 目标板卡
        board_lanes: 该板卡上的通道-Lane映射
        
    Returns:
        合并后的物理Lane，包含所有操作的时间戳
    """
    physical_ops: List[PhysicalOperation] = []
    
    for channel, lane in board_lanes.items():
        timestamp = 0
        for op in lane.operations:
            # 只记录实际的 TTL 状态变化
            if op.operation_type in [OperationType.TTL_INIT, OperationType.TTL_ON, OperationType.TTL_OFF]:
                physical_ops.append(PhysicalOperation(op, timestamp))
            
            # 累积时间戳（所有操作都占用时间）
            timestamp += op.duration_cycles
    
    # 按时间戳排序
    physical_ops.sort(key=lambda pop: pop.timestamp_cycles)
    
    return PhysicalLane(board, tuple(physical_ops))