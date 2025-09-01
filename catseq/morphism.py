"""
Morphism class and composition operations.

This module implements the core Morphism class with composition operators
and state inference logic for building complex quantum control sequences.
"""

from dataclasses import dataclass
from typing import Dict, Callable, List, Self


from .lanes import Lane
from .time_utils import cycles_to_us, us_to_cycles
from .types.common import AtomicMorphism, Board, Channel, OperationType, State
from .types.rwg import RWGUninitialized
from .types.ttl import TTLState


@dataclass(frozen=True)
class Morphism:
    """组合 Morphism - 多通道操作的集合"""
    lanes: Dict[Channel, Lane]
    _duration_cycles: int = -1  # 内部使用，用于无通道的IdentityMorphism

    def __post_init__(self):
        """验证所有Lane的时长一致（Monoidal Category要求）"""
        if not self.lanes:
            if self._duration_cycles < 0:
                # This is a true empty morphism, which is fine.
                pass
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
            return self._duration_cycles if self._duration_cycles >= 0 else 0
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

        特殊处理无通道的 IdentityMorphism，将其追加到所有 lane。
        """
        # Case 1: Morphism >> channelless IdentityMorphism
        if isinstance(other, Morphism) and not other.lanes and other.total_duration_cycles > 0:
            if not self.lanes:
                # identity >> identity just returns the longer identity
                return self if self.total_duration_cycles >= other.total_duration_cycles else other

            new_lanes = {}
            for channel, lane in self.lanes.items():
                # 从最后一个非IDENTITY操作中推断状态
                inferred_state = None
                for op in reversed(lane.operations):
                    if op.operation_type != OperationType.IDENTITY:
                        inferred_state = op.end_state
                        break
                
                # 如果通道只包含IDENTITY操作，则使用第一个操作的状态
                if inferred_state is None:
                    # This can happen if a lane is just an identity operation.
                    # The state is constant through identity, so start_state is fine.
                    inferred_state = lane.operations[0].start_state

                identity_for_channel = AtomicMorphism(
                    channel=channel,
                    start_state=inferred_state,
                    end_state=inferred_state,
                    duration_cycles=other.total_duration_cycles,
                    operation_type=OperationType.IDENTITY
                )
                new_lanes[channel] = Lane(lane.operations + (identity_for_channel,))
            return Morphism(new_lanes)

        # Case 2: Morphism >> Morphism (standard composition)
        elif isinstance(other, Morphism):
            return auto_compose_morphisms(self, other)

        # Case 3: Unsupported type
        return NotImplemented
    
    def __or__(self, other) -> 'Morphism':
        """并行组合操作符 | 
        
        将两个Morphism并行执行，要求时长相等
        """
        if isinstance(other, AtomicMorphism):
            other = from_atomic(other)
            
        return parallel_compose_morphisms(self, other)
    
    def __str__(self):
        if not self.lanes:
            # Handle channelless identity morphism
            if self.total_duration_cycles > 0:
                return f"Identity({self.total_duration_us:.1f}μs)"
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
            if self.total_duration_cycles > 0:
                return f"Identity Morphism ({self.total_duration_us:.1f}μs)"
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
                elif op.operation_type == OperationType.IDENTITY:
                    duration_us = cycles_to_us(op.duration_cycles)
                    ops_display.append(f"identity({duration_us:.1f}μs)")
            
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
        # This case is now handled by the identity() factory, which returns
        # a channelless Morphism directly. This function is for channel-bound atomics.
        raise ValueError("Cannot create Morphism from an AtomicMorphism without a channel.")
    
    lane = Lane((op,))
    return Morphism({op.channel: lane})

def identity(duration_us: float) -> "Morphism":
    """Creates a channelless identity morphism (a pure wait)."""
    duration_cycles = us_to_cycles(duration_us)
    if duration_cycles < 0:
        raise ValueError("Identity duration must be non-negative.")
    return Morphism(lanes={}, _duration_cycles=duration_cycles)


def strict_compose_morphisms(first: Morphism, second: Morphism) -> Morphism:
    """严格状态匹配组合 (@)
    
    要求first的所有通道结束状态与second的开始状态严格匹配
    """
    # 获取first的结束状态
    first_end_states = {}
    for channel, lane in first.lanes.items():
        last_op = lane.operations[-1]
        if last_op.operation_type != OperationType.IDENTITY:
            first_end_states[channel] = last_op.end_state
    
    # 获取second的开始状态
    second_start_states = {}
    for channel, lane in second.lanes.items():
        first_op = lane.operations[0]
        if first_op.operation_type != OperationType.IDENTITY:
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
        
        # 如果某个morphism中没有该通道，需要填充identity操作
        if channel not in first.lanes:
            # 填充first的空缺
            duration = first.total_duration_cycles
            identity_op = AtomicMorphism(
                channel, second_start_states[channel], second_start_states[channel],
                duration, OperationType.IDENTITY
            )
            first_ops = (identity_op,)
        
        if channel not in second.lanes:
            # 填充second的空缺
            duration = second.total_duration_cycles
            identity_op = AtomicMorphism(
                channel, first_end_states[channel], first_end_states[channel],
                duration, OperationType.IDENTITY
            )
            second_ops = (identity_op,)
        
        combined_ops = first_ops + second_ops
        result_lanes[channel] = Lane(combined_ops)
    
    return Morphism(result_lanes)


def auto_compose_morphisms(first: Morphism, second: Morphism) -> Morphism:
    """自动状态推断组合 (>>)
    
    自动推断identity操作的状态，处理通道不完全匹配的情况
    """
    # channelless identity is handled in __rshift__ now.
    if not second.lanes:
        return first
    
    # 获取first的结束状态
    first_end_states = {}
    for channel, lane in first.lanes.items():
        # 从最后一个非IDENTITY操作中推断状态
        inferred_state = None
        for op in reversed(lane.operations):
            if op.operation_type != OperationType.IDENTITY:
                inferred_state = op.end_state
                break
        if inferred_state is not None:
            first_end_states[channel] = inferred_state
        else: # Lane only contains IDENTITY ops
            first_end_states[channel] = lane.operations[0].start_state

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
                channel, first_state, first_state, duration, OperationType.IDENTITY
            )
            first_ops = (identity_op,)
            
        elif channel not in second.lanes and channel in first.lanes:
            # 在second中添加identity操作
            end_state = first_end_states[channel]
            duration = second.total_duration_cycles
            identity_op = AtomicMorphism(
                channel, end_state, end_state, duration, OperationType.IDENTITY
            )
            second_ops = (identity_op,)
        
        # 状态推断: 如果second的某个lane以identity开头，则填充状态
        new_second_ops = []
        ops_iterator = iter(second_ops)
        
        for op in ops_iterator:
            if op.operation_type == OperationType.IDENTITY:
                inferred_state = first_end_states.get(channel, TTLState.OFF) # Default state
                new_second_ops.append(AtomicMorphism(
                    op.channel if op.channel else channel,
                    inferred_state, inferred_state,
                    op.duration_cycles, op.operation_type
                ))
            else:
                new_second_ops.append(op)
                # Once we see a non-identity op, the rest don't need inference
                new_second_ops.extend(ops_iterator)
                break
        second_ops = tuple(new_second_ops)

        combined_ops = first_ops + second_ops
        result_lanes[channel] = Lane(combined_ops)
    
    return Morphism(result_lanes)


def parallel_compose_morphisms(left: Morphism, right: Morphism) -> Morphism:
    """并行组合操作 (|)
    
    将两个Morphism并行执行。如果长度不同，使用 `>> identity()` 逻辑对齐。
    """
    # 检查通道是否重叠
    overlapping_channels = set(left.lanes.keys()) & set(right.lanes.keys())
    if overlapping_channels:
        channel_names = [ch.global_id for ch in overlapping_channels]
        raise ValueError(f"Cannot compose: overlapping channels {channel_names}")

    # 获取两个morphism的时长
    left_duration = left.total_duration_cycles
    right_duration = right.total_duration_cycles

    # 如果时长相等，直接合并
    if left_duration == right_duration:
        result_lanes = {**left.lanes, **right.lanes}
        return Morphism(result_lanes)

    # 利用 >> identity() 逻辑补齐
    if left_duration < right_duration:
        padding_cycles = right_duration - left_duration
        padding_us = cycles_to_us(padding_cycles)
        # identity() returns a channelless Morphism, >> will broadcast it
        left = left >> identity(padding_us)
    elif right_duration < left_duration:
        padding_cycles = left_duration - right_duration
        padding_us = cycles_to_us(padding_cycles)
        # identity() returns a channelless Morphism, >> will broadcast it
        right = right >> identity(padding_us)

    # 合并lanes
    result_lanes = {**left.lanes, **right.lanes}
    return Morphism(result_lanes)

# --- Morphism Builder Pattern ---

class MorphismDef:
    """
    Represents a deferred-execution 'recipe' for a morphism.
    It wraps a generator function that produces a Morphism when provided
    with a channel and a starting state.
    """

    def __init__(self, generator: Callable[[Channel, State], Morphism]):
        self._generator = generator

    def __call__(self, channel: Channel, start_state: State | None = None) -> Morphism:
        """Executes the generator to produce a concrete Morphism."""
        if start_state is None:
            start_state = RWGUninitialized() # Default start for RWG
        return self._generator(channel, start_state)

    def __rshift__(self, other: Self) -> 'MorphismSequence':
        """Composes this definition with another in a sequence."""
        if isinstance(other, MorphismSequence):
            return MorphismSequence(self, *other.defs)
        return MorphismSequence(self, other)

class MorphismSequence:
    """
    Represents a sequence of MorphismDefs to be executed in order.
    """

    def __init__(self, *defs: MorphismDef):
        self.defs = list(defs)

    def __rshift__(self, other: MorphismDef) -> Self:
        """Appends another MorphismDef to the sequence."""
        self.defs.append(other)
        return self

    def __call__(self, channel: Channel, start_state: State | None = None) -> Morphism:
        """Executes the full sequence of generators."""
        if start_state is None:
            start_atate = RWGUninitialized()

        if not self.defs:
            return Morphism(lanes={})

        # Execute the first generator
        current_morphism = self.defs[0](channel, start_state)

        # Iteratively compose the rest
        for next_def in self.defs[1:]:
            # The next start state is the end state of the current morphism
            # This assumes single-channel operation for now.
            if channel not in current_morphism.lanes:
                # If the first morphism was just an identity, the state is unchanged
                next_start_state = start_state
            else:
                last_op = current_morphism.lanes[channel].operations[-1]
                # Infer state from last non-identity op
                inferred_state = None
                for op in reversed(current_morphism.lanes[channel].operations):
                    if op.operation_type != OperationType.IDENTITY:
                        inferred_state = op.end_state
                        break
                next_start_state = inferred_state if inferred_state is not None else last_op.start_state

            next_morphism_piece = next_def(channel, next_start_state)
            
            # Use the Morphism's own composition logic
            current_morphism = current_morphism >> next_morphism_piece

        return current_morphism