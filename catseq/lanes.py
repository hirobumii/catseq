"""
Lane and physical operation management.

This module handles the physical representation of operations, including Lane
objects that group operations by channel and PhysicalLane objects that merge
operations across multiple channels for hardware execution.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .types import AtomicMorphism, Board, Channel, OperationType
from .time_utils import cycles_to_us


@dataclass(frozen=True)
class Lane:
    """通道 Lane - 单个通道的操作序列"""
    operations: Tuple[AtomicMorphism, ...]  # 操作序列
    _total_duration_cycles: int = field(init=False, repr=False)
    _initial_state: object | None = field(init=False, repr=False)
    _end_state: object | None = field(init=False, repr=False)
    _effective_start_state: object | None = field(init=False, repr=False)
    _effective_end_state: object | None = field(init=False, repr=False)

    def __post_init__(self):
        total_duration = 0
        initial_state = None
        end_state = None
        effective_start_state = None
        effective_end_state = None

        if self.operations:
            initial_state = getattr(self.operations[0], "start_state", None)
            end_state = getattr(self.operations[-1], "end_state", None)
            total_duration = sum(getattr(op, "duration_cycles", 0) for op in self.operations)

            for op in self.operations:
                if getattr(op, "operation_type", None) != OperationType.IDENTITY:
                    effective_start_state = getattr(op, "start_state", None)
                    break
            if effective_start_state is None:
                effective_start_state = initial_state

            for op in reversed(self.operations):
                if getattr(op, "operation_type", None) != OperationType.IDENTITY:
                    effective_end_state = getattr(op, "end_state", None)
                    break
            if effective_end_state is None:
                effective_end_state = end_state

        object.__setattr__(self, "_total_duration_cycles", total_duration)
        object.__setattr__(self, "_initial_state", initial_state)
        object.__setattr__(self, "_end_state", end_state)
        object.__setattr__(self, "_effective_start_state", effective_start_state)
        object.__setattr__(self, "_effective_end_state", effective_end_state)
    
    @property
    def total_duration_cycles(self) -> int:
        """总时长（时钟周期）"""
        return self._total_duration_cycles
    
    @property
    def total_duration_us(self) -> float:
        """总时长（微秒）"""
        return cycles_to_us(self.total_duration_cycles)

    @property
    def initial_state(self):
        return self._initial_state

    @property
    def end_state(self):
        return self._end_state

    @property
    def effective_start_state(self):
        return self._effective_start_state

    @property
    def effective_end_state(self):
        return self._effective_end_state
    
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
            # Skip IDENTITY operations - they are only for timing alignment
            if op.operation_type != OperationType.IDENTITY:
                physical_ops.append(PhysicalOperation(op, timestamp))
            
            # 累积时间戳（所有操作都占用时间，包括IDENTITY）
            timestamp += op.duration_cycles

    # Keep all operations and defer any board-scoped blackbox collapsing to the compiler
    # pipeline, where full board/timestamp context is available. The secondary sort key
    # makes same-timestamp ordering deterministic across versions.
    physical_ops.sort(
        key=lambda pop: (
            pop.timestamp_cycles,
            pop.operation.channel.global_id if pop.operation.channel else "",
        )
    )

    return PhysicalLane(board, tuple(physical_ops))
