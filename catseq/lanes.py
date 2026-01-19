"""
Lane and physical operation management.

This module handles the physical representation of operations, including Lane
objects that group operations by channel and PhysicalLane objects that merge
operations across multiple channels for hardware execution.
"""

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .types import AtomicMorphism, Board, Channel, OperationType
from .types.common import BlackBoxAtomicMorphism
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
    
    对于涉及同一板卡多个通道的 blackbox 操作，只保留一个 LogicalEvent。
    
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
            # Skip IDENTITY operations - they are only for timing alignment
            if op.operation_type != OperationType.IDENTITY:
                physical_ops.append(PhysicalOperation(op, timestamp))
            
            # 累积时间戳（所有操作都占用时间，包括IDENTITY）
            timestamp += op.duration_cycles
    
    # 按时间戳排序
    physical_ops.sort(key=lambda pop: pop.timestamp_cycles)
    
    # Deduplicate blackbox operations at the same timestamp
    # Group operations by timestamp
    ops_by_timestamp: Dict[int, List[PhysicalOperation]] = {}
    for pop in physical_ops:
        ts = pop.timestamp_cycles
        if ts not in ops_by_timestamp:
            ops_by_timestamp[ts] = []
        ops_by_timestamp[ts].append(pop)
    
    # Deduplicate blackbox operations within each timestamp group
    deduplicated_ops: List[PhysicalOperation] = []
    for ts in sorted(ops_by_timestamp.keys()):
        ts_ops = ops_by_timestamp[ts]
        
        # Separate blackbox and non-blackbox operations
        blackbox_ops = [pop for pop in ts_ops if isinstance(pop.operation, BlackBoxAtomicMorphism)]
        non_blackbox_ops = [pop for pop in ts_ops if not isinstance(pop.operation, BlackBoxAtomicMorphism)]
        
        # For blackbox operations, group by user_func and keep only one per unique function
        if blackbox_ops:
            seen_funcs = set()
            unique_blackbox_ops = []
            for pop in blackbox_ops:
                func_id = id(pop.operation.user_func)
                if func_id not in seen_funcs:
                    seen_funcs.add(func_id)
                    unique_blackbox_ops.append(pop)
            
            # Add deduplicated blackbox ops and all non-blackbox ops
            deduplicated_ops.extend(non_blackbox_ops)
            deduplicated_ops.extend(unique_blackbox_ops)
        else:
            # No blackbox operations, just add all ops
            deduplicated_ops.extend(ts_ops)
    
    # Sort again to maintain timestamp order
    deduplicated_ops.sort(key=lambda pop: pop.timestamp_cycles)
    
    return PhysicalLane(board, tuple(deduplicated_ops))