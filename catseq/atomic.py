"""
Atomic operations and AtomicMorphism implementation.

This module contains the AtomicMorphism class and factory functions for creating
atomic operations like TTL state changes and wait operations.
"""

from dataclasses import dataclass
from typing import Optional

from .types import Channel, TTLState, OperationType
from .time_utils import us_to_cycles


@dataclass(frozen=True)
class AtomicMorphism:
    """原子 Morphism - 基本操作单元"""
    channel: Optional[Channel]  # wait morphism 没有特定通道
    start_state: Optional[TTLState]  # wait morphism 在组合时确定
    end_state: Optional[TTLState]    # wait morphism 在组合时确定
    duration_cycles: int  # 操作时长（时钟周期）
    operation_type: OperationType  # 操作类型标识
    
    def __post_init__(self):
        if self.duration_cycles < 0:
            raise ValueError(f"Duration must be non-negative, got {self.duration_cycles} cycles")
        
        # 验证状态转移是否合法
        if self.channel is not None and self.start_state is not None and self.end_state is not None:
            self._validate_state_transition()
    
    def _validate_state_transition(self):
        """验证 TTL 状态转移是否合法"""
        valid_transitions = {
            TTLState.UNINITIALIZED: {TTLState.OFF},  # 初始化
            TTLState.OFF: {TTLState.ON, TTLState.OFF},  # 可以开启或保持
            TTLState.ON: {TTLState.OFF, TTLState.ON}   # 可以关闭或保持
        }
        
        if self.end_state not in valid_transitions.get(self.start_state, set()):
            raise ValueError(
                f"Invalid TTL state transition: {self.start_state} → {self.end_state}"
            )
    
    def __str__(self):
        if self.operation_type == OperationType.WAIT:
            duration_us = self.duration_cycles / 250  # 250 cycles per μs
            return f"wait({duration_us:.1f}μs)"
        elif self.channel:
            return f"{self.operation_type.name.lower()}"
        else:
            return f"{self.operation_type.name.lower()}({self.duration_cycles})"


# Factory functions for creating atomic operations

def ttl_init(channel: Channel) -> AtomicMorphism:
    """创建 TTL 初始化操作: UNINITIALIZED → OFF
    
    Args:
        channel: 目标通道
        
    Returns:
        TTL 初始化的原子操作
    """
    return AtomicMorphism(
        channel=channel,
        start_state=TTLState.UNINITIALIZED,
        end_state=TTLState.OFF,
        duration_cycles=1,  # 1 cycle for initialization
        operation_type=OperationType.TTL_INIT
    )


def ttl_on(channel: Channel) -> AtomicMorphism:
    """创建 TTL 开启操作: OFF → ON
    
    Args:
        channel: 目标通道
        
    Returns:
        TTL 开启的原子操作
    """
    return AtomicMorphism(
        channel=channel,
        start_state=TTLState.OFF,
        end_state=TTLState.ON,
        duration_cycles=1,  # 1 cycle for state change
        operation_type=OperationType.TTL_ON
    )


def ttl_off(channel: Channel) -> AtomicMorphism:
    """创建 TTL 关闭操作: ON → OFF
    
    Args:
        channel: 目标通道
        
    Returns:
        TTL 关闭的原子操作
    """
    return AtomicMorphism(
        channel=channel,
        start_state=TTLState.ON,
        end_state=TTLState.OFF,
        duration_cycles=1,  # 1 cycle for state change
        operation_type=OperationType.TTL_OFF
    )


def wait(duration_us: float) -> AtomicMorphism:
    """创建等待操作
    
    Args:
        duration_us: 等待时长（微秒）
        
    Returns:
        等待操作的原子形态
    """
    return AtomicMorphism(
        channel=None,  # 等待操作不特定于某个通道
        start_state=None,  # 在组合时推断
        end_state=None,    # 在组合时推断  
        duration_cycles=us_to_cycles(duration_us),
        operation_type=OperationType.WAIT
    )