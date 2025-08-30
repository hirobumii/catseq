"""
Morphism class and composition operations.

This module implements the core Morphism class with composition operators
and state inference logic for building complex quantum control sequences.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Union

from .types import Board, Channel, TTLState, OperationType
from .atomic import AtomicMorphism
from .lanes import Lane, PhysicalLane, merge_board_lanes
from .time_utils import cycles_to_us


@dataclass(frozen=True)
class Morphism:
    """组合 Morphism - 多通道操作的集合"""
    lanes: Dict[Channel, Lane]
    
    def __post_init__(self):
        """验证所有Lane的时长一致（Monoidal Category要求）"""
        if not self.lanes:
            return
            
        durations = [lane.total_duration_cycles for lane in self.lanes.values()]
        if len(set(durations)) > 1:
            duration_strs = [f"{cycles_to_us(d):.1f}μs" for d in durations]
            raise ValueError(
                f"All lanes must have equal duration for parallel composition. "
                f"Got: {duration_strs}"
            )
    
    @property
    def total_duration_cycles(self) -> int:
        """总时长（时钟周期）"""
        if not self.lanes:
            return 0
        return next(iter(self.lanes.values())).total_duration_cycles
    
    @property
    def total_duration_us(self) -> float:
        """总时长（微秒）"""
        return cycles_to_us(self.total_duration_cycles)
    
    def lanes_by_board(self) -> Dict[Board, Dict[Channel, Lane]]:
        """按板卡分组的通道-Lane映射"""
        result: Dict[Board, Dict[Channel, Lane]] = {}
        for channel, lane in self.lanes.items():
            board = channel.board
            if board not in result:
                result[board] = {}
            result[board][channel] = lane
        return result
    
    def __matmul__(self, other) -> 'Morphism':
        """严格状态匹配组合操作符 @
        
        要求左侧所有通道的结束状态完全匹配右侧的开始状态
        """
        if isinstance(other, AtomicMorphism):
            other = from_atomic(other)
            
        return strict_compose_morphisms(self, other)
    
    def __rshift__(self, other) -> 'Morphism':
        """自动状态推断组合操作符 >>
        
        自动推断wait操作的状态，处理通道不匹配的情况
        """
        if isinstance(other, AtomicMorphism):
            other = from_atomic(other)
            
        return auto_compose_morphisms(self, other)
    
    def __or__(self, other) -> 'Morphism':
        """并行组合操作符 |
        
        将两个Morphism并行执行，要求时长相等
        """
        if isinstance(other, AtomicMorphism):
            other = from_atomic(other)
            
        return parallel_compose_morphisms(self, other)
    
    def __str__(self):
        if not self.lanes:
            return "EmptyMorphism"
        
        # 按板卡分组显示
        board_summary = []
        for board, board_lanes in self.lanes_by_board().items():
            channel_list = []
            for channel, lane in sorted(board_lanes.items(), key=lambda x: x[0].local_id):
                channel_desc = f"ch{channel.local_id}:{lane}"
                channel_list.append(channel_desc)
            board_summary.append(f"{board.id}[{','.join(channel_list)}]")
        
        total_duration = self.total_duration_us
        return f"⚡ {','.join(board_summary)} ({total_duration:.1f}μs)"
    
    def lanes_view(self) -> str:
        """生成详细的通道视图"""
        if not self.lanes:
            return "Empty Morphism"
        
        lines = []
        lines.append(f"Lanes View ({self.total_duration_us:.1f}μs):")
        lines.append("=" * 80)
        
        # 按板卡和通道ID排序显示
        sorted_channels = sorted(self.lanes.keys(), key=lambda ch: (ch.board.id, ch.local_id))
        
        for channel in sorted_channels:
            lane = self.lanes[channel]
            
            # 构建操作序列显示
            ops_display = []
            for op in lane.operations:
                if op.operation_type == OperationType.TTL_INIT:
                    ops_display.append("init")
                elif op.operation_type == OperationType.TTL_ON:
                    ops_display.append("ON")
                elif op.operation_type == OperationType.TTL_OFF:
                    ops_display.append("OFF")
                elif op.operation_type == OperationType.WAIT:
                    duration_us = cycles_to_us(op.duration_cycles)
                    ops_display.append(f"wait({duration_us:.1f}μs)")
            
            line = f"{channel.global_id:<20} │ {' → '.join(ops_display)}"
            lines.append(line)
        
        return "\n".join(lines)


def from_atomic(op: AtomicMorphism) -> Morphism:
    """将原子操作转换为Morphism
    
    Args:
        op: 原子操作
        
    Returns:
        包含单个操作的Morphism
    """
    if op.channel is None:
        # wait操作没有特定通道，返回空Morphism
        # 在实际组合中，wait会被分配到所有相关通道
        return Morphism({})
    
    lane = Lane((op,))
    return Morphism({op.channel: lane})


def strict_compose_morphisms(first: Morphism, second: Morphism) -> Morphism:
    """严格状态匹配组合 (@)
    
    要求first的所有通道结束状态与second的开始状态严格匹配
    """
    # 获取first的结束状态
    first_end_states = {}
    for channel, lane in first.lanes.items():
        last_op = lane.operations[-1]
        if last_op.operation_type != OperationType.WAIT:
            first_end_states[channel] = last_op.end_state
    
    # 获取second的开始状态
    second_start_states = {}
    for channel, lane in second.lanes.items():
        first_op = lane.operations[0]
        if first_op.operation_type != OperationType.WAIT:
            second_start_states[channel] = first_op.start_state
    
    # 验证状态匹配
    for channel in first_end_states:
        if channel in second_start_states:
            if first_end_states[channel] != second_start_states[channel]:
                raise ValueError(
                    f"State mismatch for channel {channel}: "
                    f"{first_end_states[channel]} → {second_start_states[channel]}"
                )
    
    # 合并lanes
    result_lanes = {}
    all_channels = set(first.lanes.keys()) | set(second.lanes.keys())
    
    for channel in all_channels:
        first_ops = first.lanes.get(channel, Lane(())).operations
        second_ops = second.lanes.get(channel, Lane(())).operations
        
        # 如果某个morphism中没有该通道，需要填充identity/wait操作
        if channel not in first.lanes:
            # 填充first的空缺
            duration = first.total_duration_cycles
            identity_op = AtomicMorphism(
                channel, second_start_states[channel], second_start_states[channel],
                duration, OperationType.WAIT
            )
            first_ops = (identity_op,)
        
        if channel not in second.lanes:
            # 填充second的空缺
            duration = second.total_duration_cycles
            identity_op = AtomicMorphism(
                channel, first_end_states[channel], first_end_states[channel],
                duration, OperationType.WAIT
            )
            second_ops = (identity_op,)
        
        combined_ops = first_ops + second_ops
        result_lanes[channel] = Lane(combined_ops)
    
    return Morphism(result_lanes)


def auto_compose_morphisms(first: Morphism, second: Morphism) -> Morphism:
    """自动状态推断组合 (>>)
    
    自动推断wait操作的状态，处理通道不完全匹配的情况
    """
    # 如果second是wait操作（空lanes），分配到first的所有通道
    if not second.lanes:
        # 假设这是一个wait操作，需要从atomic形式推断
        # 这种情况在实际使用中会通过合适的工厂函数处理
        return first
    
    # 获取first的结束状态
    first_end_states = {}
    for channel, lane in first.lanes.items():
        last_op = lane.operations[-1]
        if last_op.operation_type != OperationType.WAIT:
            first_end_states[channel] = last_op.end_state
        else:
            # wait操作保持前一个非wait操作的状态
            for op in reversed(lane.operations):
                if op.operation_type != OperationType.WAIT:
                    first_end_states[channel] = op.end_state
                    break
    
    # 合并lanes，自动填充状态
    result_lanes = {}
    all_channels = set(first.lanes.keys()) | set(second.lanes.keys())
    
    for channel in all_channels:
        first_ops = first.lanes.get(channel, Lane(())).operations
        second_ops = second.lanes.get(channel, Lane(())).operations
        
        # 处理通道缺失的情况
        if channel not in first.lanes and channel in second.lanes:
            # 在first中添加identity操作
            first_state = second.lanes[channel].operations[0].start_state
            duration = first.total_duration_cycles
            identity_op = AtomicMorphism(
                channel, first_state, first_state, duration, OperationType.WAIT
            )
            first_ops = (identity_op,)
            
        elif channel not in second.lanes and channel in first.lanes:
            # 在second中添加identity操作
            end_state = first_end_states[channel]
            duration = second.total_duration_cycles
            identity_op = AtomicMorphism(
                channel, end_state, end_state, duration, OperationType.WAIT
            )
            second_ops = (identity_op,)
        
        # 处理wait操作的状态推断
        if second_ops and second_ops[0].operation_type == OperationType.WAIT:
            # 推断wait操作的状态
            inferred_state = first_end_states.get(channel, TTLState.OFF)
            second_ops = tuple(
                AtomicMorphism(
                    op.channel if op.channel else channel,
                    inferred_state, inferred_state,
                    op.duration_cycles, op.operation_type
                ) if op.operation_type == OperationType.WAIT else op
                for op in second_ops
            )
        
        combined_ops = first_ops + second_ops
        result_lanes[channel] = Lane(combined_ops)
    
    return Morphism(result_lanes)


def parallel_compose_morphisms(left: Morphism, right: Morphism) -> Morphism:
    """并行组合操作 (|)
    
    将两个Morphism并行执行，要求时长相等
    """
    # 检查时长是否相等
    if left.total_duration_cycles != right.total_duration_cycles:
        raise ValueError(
            f"Cannot compose morphisms with different durations: "
            f"{left.total_duration_us:.1f}μs vs {right.total_duration_us:.1f}μs"
        )
    
    # 检查通道是否重叠
    overlapping_channels = set(left.lanes.keys()) & set(right.lanes.keys())
    if overlapping_channels:
        channel_names = [ch.global_id for ch in overlapping_channels]
        raise ValueError(f"Cannot compose: overlapping channels {channel_names}")
    
    # 简单合并lanes
    result_lanes = {**left.lanes, **right.lanes}
    return Morphism(result_lanes)