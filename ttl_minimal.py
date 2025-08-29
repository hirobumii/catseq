#!/usr/bin/env python3
"""
TTL 最小实现 - 从 Monoidal Category 到 OASM DSL
基于 TTL_MINIMAL_IMPLEMENTATION.md 的设计
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Union, List


# === 时间单位转换 ===

# RTMQ 时钟频率：250 MHz
CLOCK_FREQ_HZ = 250_000_000
CYCLES_PER_US = 250  # 1微秒 = 250个时钟周期

def us_to_cycles(microseconds: float) -> int:
    """将微秒转换为时钟周期（整数）"""
    cycles = int(microseconds * CYCLES_PER_US)
    if cycles < 0:
        raise ValueError(f"Time cannot be negative: {microseconds}us")
    return cycles

def cycles_to_us(cycles: int) -> float:
    """将时钟周期转换为微秒"""
    return cycles / CYCLES_PER_US


# === 基础数据结构 ===

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
    UNINITIALIZED = -1  # 通道未初始化状态
    OFF = 0            # 通道关闭（输出低电平）
    ON = 1             # 通道开启（输出高电平）
    
    def __str__(self):
        return self.name


class OperationType(Enum):
    """操作类型枚举"""
    # TTL 操作
    TTL_INIT = "ttl_init"
    TTL_ON = "ttl_on"
    TTL_OFF = "ttl_off"
    
    # 时间操作
    WAIT = "wait"
    
    # RWG 操作（为将来扩展预留）
    RWG_SET_FREQ = "rwg_set_freq"
    RWG_LINEAR_RAMP = "rwg_linear_ramp"
    RWG_PHASE_SHIFT = "rwg_phase_shift"
    RWG_AMPLITUDE_MOD = "rwg_amplitude_mod"
    
    def __str__(self):
        return self.value


@dataclass(frozen=True)
class Lane:
    """单通道上的操作序列"""
    operations: tuple[AtomicMorphism, ...]  # 不可变的操作序列
    
    @property
    def start_state(self) -> Optional[TTLState]:
        """Lane 的起始状态"""
        return self.operations[0].start_state if self.operations else None
    
    @property 
    def end_state(self) -> Optional[TTLState]:
        """Lane 的结束状态"""
        return self.operations[-1].end_state if self.operations else None
    
    @property
    def total_duration_cycles(self) -> int:
        """Lane 的总时长（时钟周期）"""
        return sum(op.duration_cycles for op in self.operations)
    
    @property
    def total_duration_us(self) -> float:
        """Lane 的总时长（微秒）"""
        return cycles_to_us(self.total_duration_cycles)


@dataclass(frozen=True)
class PhysicalOperation:
    """物理操作 - 同一时刻在同一板卡上的合并操作"""
    board: Board
    timestamp_cycles: int      # 绝对时间戳（时钟周期）
    duration_cycles: int       # 操作持续时间（时钟周期）
    operation_type: str        # 操作类型：'ttl_set', 'wait', 'identity'
    channel_mask: int          # TTL通道位掩码，如 0x03 表示通道0和1
    target_states: Dict[int, TTLState]  # 通道号 -> 目标状态
    
    @property
    def timestamp_us(self) -> float:
        """时间戳（微秒，仅用于显示）"""
        return cycles_to_us(self.timestamp_cycles)
    
    @property 
    def duration_us(self) -> float:
        """持续时间（微秒，仅用于显示）"""
        return cycles_to_us(self.duration_cycles)
    
    @property
    def end_timestamp_cycles(self) -> int:
        """结束时间戳（时钟周期）"""
        return self.timestamp_cycles + self.duration_cycles


@dataclass(frozen=True)
class PhysicalLane:
    """物理Lane - 单个板卡的时序操作序列"""
    board: Board
    operations: tuple[PhysicalOperation, ...]
    
    @property
    def total_duration_cycles(self) -> int:
        """总时长（时钟周期）"""
        return max((op.end_timestamp_cycles for op in self.operations), default=0)
    
    @property
    def total_duration_us(self) -> float:
        """总时长（微秒，仅用于显示）"""
        return cycles_to_us(self.total_duration_cycles)


def merge_board_lanes(board: Board, board_lanes: Dict[Channel, Lane]) -> PhysicalLane:
    """将同一板卡上的多个逻辑Lane合并为单个PhysicalLane
    
    基于时间戳重新编排，只保留实际的硬件操作（TTL状态变化）
    wait/identity 操作只是时间间隔，不生成物理操作
    """
    # 收集所有 TTL 状态变化事件
    ttl_events: Dict[int, Dict[int, TTLState]] = {}  # timestamp -> {channel_local_id: target_state}
    
    for channel, lane in board_lanes.items():
        timestamp = 0
        for op in lane.operations:
            # 只记录实际的 TTL 状态变化
            if op.operation_type in [OperationType.TTL_INIT, OperationType.TTL_ON, OperationType.TTL_OFF]:
                if timestamp not in ttl_events:
                    ttl_events[timestamp] = {}
                ttl_events[timestamp][channel.local_id] = op.end_state
            
            # 累积时间戳（所有操作都占用时间）
            timestamp += op.duration_cycles
    
    # 为每个时间戳创建合并的 TTL 操作
    physical_ops = []
    for timestamp_cycles in sorted(ttl_events.keys()):
        channel_states = ttl_events[timestamp_cycles]
        
        # 创建位掩码和状态映射
        channel_mask = 0
        target_states = {}
        for channel_id, target_state in channel_states.items():
            channel_mask |= (1 << channel_id)
            target_states[channel_id] = target_state
        
        # 所有 TTL 操作都是瞬时的（1个时钟周期）
        physical_ops.append(PhysicalOperation(
            board=board,
            timestamp_cycles=timestamp_cycles,
            duration_cycles=1,  # TTL 操作瞬时完成
            operation_type='ttl_set',  # 保持字符串，这是硬件层的操作类型
            channel_mask=channel_mask,
            target_states=target_states
        ))
    
    return PhysicalLane(board=board, operations=tuple(physical_ops))


# === OASM 序列生成器 ===

# 首先定义一些示例函数（用户需要根据实际情况替换）
def ttl_config(value, mask):
    """TTL 配置函数示例"""
    pass

def wait_us(duration):
    """等待函数示例"""
    pass

def my_wait():
    """自定义等待函数示例"""
    pass

def trig_slave(param):
    """触发从机函数示例"""
    pass

class OASMAddress(Enum):
    """OASM 地址枚举"""
    MAIN = "main"
    RWG0 = "rwg0"
    RWG1 = "rwg1" 
    RWG2 = "rwg2"
    RWG3 = "rwg3"
    RWG4 = "rwg4"
    RWG5 = "rwg5"
    RWG6 = "rwg6"
    RWG7 = "rwg7"

class OASMFunction(Enum):
    """OASM DSL 函数枚举 - 存储实际的函数对象"""
    # TTL 函数
    TTL_CONFIG = ttl_config
    
    # 时间函数
    WAIT_US = wait_us
    MY_WAIT = my_wait
    
    # 触发函数
    TRIG_SLAVE = trig_slave

@dataclass(frozen=True)
class OASMCall:
    """单个 OASM 调用：seq(adr, dsl_func, *args, **kwargs)"""
    adr: OASMAddress           # 地址枚举
    dsl_func: OASMFunction     # DSL 函数枚举
    args: tuple = ()           # 位置参数
    kwargs: dict = None        # 关键字参数
    
    def __post_init__(self):
        if self.kwargs is None:
            object.__setattr__(self, 'kwargs', {})

def compile_to_oasm_calls(morphism: Morphism) -> List[OASMCall]:
    """
    将 Morphism 编译为 OASM 调用序列
    
    Returns:
        OASMCall 列表，包含 seq(adr, dsl_func, *args, **kwargs) 调用信息
    """
    calls = []
    
    # 按板卡分组并生成调用
    for board, board_lanes in morphism.lanes_by_board().items():
        physical_lane = merge_board_lanes(board, board_lanes)
        
        # 将板卡ID映射到 OASMAddress
        try:
            adr = OASMAddress(board.id.lower() if hasattr(board, 'id') else str(board).lower())
        except ValueError:
            # 如果板卡ID不在枚举中，默认使用 RWG0
            adr = OASMAddress.RWG0
        
        # 为每个物理操作生成 OASM 调用
        for op in physical_lane.operations:
            if op.operation_type == 'ttl_set':
                # 生成 TTL 配置调用
                ttl_value = 0
                for ch_id, state in op.target_states.items():
                    if state == TTLState.ON:
                        ttl_value |= (1 << ch_id)
                
                calls.append(OASMCall(
                    adr=adr,
                    dsl_func=OASMFunction.TTL_CONFIG,
                    args=(ttl_value,),
                    kwargs={'mask': op.channel_mask}
                ))
                
                # 如果需要延迟，添加延迟调用
                if op.duration_cycles > 1:
                    delay_us = op.duration_us
                    calls.append(OASMCall(
                        adr=adr,
                        dsl_func=OASMFunction.WAIT_US,
                        args=(delay_us,)
                    ))
    
    return calls

def execute_oasm_calls(calls: List[OASMCall], seq_object) -> bool:
    """
    执行 OASM 调用序列
    
    Args:
        calls: OASM 调用列表
        seq_object: OASM assembler 序列对象
        
    Returns:
        是否执行成功
    """
    try:
        for call in calls:
            # 执行 seq(adr, dsl_func, *args, **kwargs)
            seq_object(call.adr.value, call.dsl_func.value, *call.args, **call.kwargs)
        
        # 运行序列
        seq_object.run()
        return True
    except Exception as e:
        print(f"OASM execution error: {e}")
        return False


@dataclass(frozen=True)
class Morphism:
    """复合 Morphism - 使用 Channel -> Lane 的映射存储"""
    lanes: Dict[Channel, Lane]  # 每个通道的操作序列
    
    @property
    def total_duration_cycles(self) -> int:
        """所有通道中的最大时长"""
        return max((lane.total_duration_cycles for lane in self.lanes.values()), default=0)
    
    @property
    def total_duration_us(self) -> float:
        """所有通道中的最大时长（微秒）"""
        return cycles_to_us(self.total_duration_cycles)
    
    @property
    def channels(self) -> set[Channel]:
        """获取涉及的所有通道"""
        return set(self.lanes.keys())
    
    @property
    def boards(self) -> set[Board]:
        """获取涉及的所有板卡"""
        return {channel.board for channel in self.channels}
    
    def get_channels_by_board(self, board: Board) -> set[Channel]:
        """获取指定板卡上的所有通道"""
        return {ch for ch in self.channels if ch.board == board}
    
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
        """@ 操作符：串行组合（严格匹配）"""
        # 如果 other 是 Morphism，进行 Morphism-to-Morphism 组合
        if isinstance(other, Morphism):
            return self._compose_morphisms(other, strict=True)
        elif isinstance(other, AtomicMorphism):
            if other.channel is None:
                # wait 操作：应用到所有通道
                return self._append_wait_to_all(other, strict=True)
            elif other.channel in self.lanes:
                # 通道已存在：追加到该通道的 Lane
                return self._append_to_channel(other, strict=True)
            else:
                # 新通道：创建新的 Lane
                return self._add_new_channel(other)
        else:
            return NotImplemented
    
    def __rshift__(self, other) -> 'Morphism':
        """>> 操作符：串行组合（自动匹配）"""
        # 如果 other 是 Morphism，进行 Morphism-to-Morphism 组合
        if isinstance(other, Morphism):
            return self._compose_morphisms(other, strict=False)
        elif isinstance(other, AtomicMorphism):
            if other.channel is None:
                # wait 操作：应用到所有通道
                return self._append_wait_to_all(other, strict=False)
            elif other.channel in self.lanes:
                # 通道已存在：追加到该通道的 Lane
                return self._append_to_channel(other, strict=False)
            else:
                # 新通道：创建新的 Lane
                return self._add_new_channel(other)
        else:
            return NotImplemented
    
    def __or__(self, other) -> 'Morphism':
        """| 操作符：并行组合（张量积）"""
        # 如果 other 是 AtomicMorphism，先转换为 Morphism
        if isinstance(other, AtomicMorphism):
            other = from_atomic(other)
        elif not isinstance(other, Morphism):
            return NotImplemented
        
        # 验证通道不重复
        overlap = self.channels & other.channels
        if overlap:
            raise ValueError(f"Cannot do tensor product: channels {overlap} appear in both morphisms")
        
        # 合并通道映射
        combined_lanes = dict(self.lanes)
        combined_lanes.update(other.lanes)
        
        # 计算最大时长并补齐所有 Lane
        max_duration = max(
            max((lane.total_duration_cycles for lane in self.lanes.values()), default=0),
            max((lane.total_duration_cycles for lane in other.lanes.values()), default=0)
        )
        
        padded_lanes = {}
        for channel, lane in combined_lanes.items():
            if lane.total_duration_cycles < max_duration:
                # 需要补齐 identity 操作
                padding_cycles = max_duration - lane.total_duration_cycles
                identity_op = AtomicMorphism(
                    channel=channel,
                    start_state=lane.end_state,
                    end_state=lane.end_state,
                    duration_cycles=padding_cycles,
                    operation_type=OperationType.WAIT
                )
                padded_lanes[channel] = Lane(operations=lane.operations + (identity_op,))
            else:
                padded_lanes[channel] = lane
        
        return Morphism(lanes=padded_lanes)
    
    def __str__(self) -> str:
        """简洁的字符串表示"""
        if not self.lanes:
            return "Morphism(empty)"
        
        # 按板卡分组显示
        board_summary = []
        for board, board_lanes in self.lanes_by_board().items():
            channels = sorted(board_lanes.keys(), key=lambda c: c.local_id)
            channel_list = [f"ch{ch.local_id}" for ch in channels]
            board_summary.append(f"{board.id}[{','.join(channel_list)}]")
        
        duration_info = f"{self.total_duration_us:.1f}μs"
        return f"Morphism({' | '.join(board_summary)}, {duration_info})"
    
    def __repr__(self) -> str:
        """详细的调试表示"""
        return self.__str__()
    
    def describe(self) -> str:
        """详细的人类可读描述"""
        if not self.lanes:
            return "Empty Morphism"
        
        lines = [f"Morphism Summary:"]
        lines.append(f"  Duration: {self.total_duration_us:.1f}μs ({self.total_duration_cycles} cycles)")
        lines.append(f"  Boards: {len(self.boards)}")
        lines.append(f"  Channels: {len(self.channels)}")
        
        lines.append("\nPer-Board Breakdown:")
        for board, board_lanes in self.lanes_by_board().items():
            lines.append(f"  📍 {board.id}:")
            lines.append(f"    Channels: {len(board_lanes)}")
            
            # 显示每个通道的操作序列
            for channel in sorted(board_lanes.keys(), key=lambda c: c.local_id):
                lane = board_lanes[channel]
                lines.append(f"    🔹 {channel}:")
                
                # 显示操作时序
                t = 0
                for i, op in enumerate(lane.operations):
                    op_desc = f"{op.operation_type}"
                    if op.operation_type in [OperationType.TTL_INIT, OperationType.TTL_ON, OperationType.TTL_OFF]:
                        op_desc += f"({op.start_state.name}→{op.end_state.name})"
                    
                    if op.duration_cycles > 1:
                        lines.append(f"      t={t/250:.1f}μs: {op_desc} +{op.duration_cycles/250:.1f}μs")
                    else:
                        lines.append(f"      t={t/250:.1f}μs: {op_desc}")
                    
                    t += op.duration_cycles
        
        return "\n".join(lines)
    
    def timeline(self) -> str:
        """全局时间线视图：显示所有通道的并行时序"""
        if not self.lanes:
            return "Empty timeline"
        
        lines = [f"Timeline View ({self.total_duration_us:.1f}μs):"]
        lines.append("=" * 60)
        
        # 收集所有时间事件
        all_events = []  # [(time_us, channel, event_description)]
        
        for channel, lane in self.lanes.items():
            t_cycles = 0
            for op in lane.operations:
                time_us = t_cycles / 250
                
                if op.operation_type in [OperationType.TTL_INIT, OperationType.TTL_ON, OperationType.TTL_OFF]:
                    event = f"{op.operation_type}({op.start_state.name}→{op.end_state.name})"
                elif op.operation_type in [OperationType.WAIT, OperationType.WAIT]:
                    event = f"{op.operation_type}({op.duration_cycles/250:.1f}μs)"
                else:
                    event = op.operation_type
                
                all_events.append((time_us, channel, event))
                t_cycles += op.duration_cycles
        
        # 按时间排序并显示
        all_events.sort(key=lambda x: x[0])
        
        for time_us, channel, event in all_events:
            lines.append(f"t={time_us:6.1f}μs  {channel}  {event}")
        
        return "\n".join(lines)
    
    def lanes_view(self) -> str:
        """Lane 并排视图：隐藏硬件细节，按通道并排显示逻辑操作序列"""
        if not self.lanes:
            return "Empty lanes"
        
        lines = [f"Lanes View ({self.total_duration_us:.1f}μs):"]
        lines.append("=" * 80)
        
        # 将操作简化为用户友好的描述
        def simplify_operation(op) -> str:
            if op.operation_type == OperationType.TTL_INIT:
                return "init"
            elif op.operation_type == OperationType.TTL_ON:
                return "ON"
            elif op.operation_type == OperationType.TTL_OFF:
                return "OFF"
            elif op.operation_type == OperationType.WAIT:
                return f"wait({op.duration_us:.1f}μs)"
            elif op.operation_type == OperationType.WAIT:
                return f"hold({op.duration_us:.1f}μs)"
            else:
                return str(op.operation_type)
        
        # 按板卡分组，然后在组内按通道号排序
        sorted_channels = []
        for board in sorted(self.boards, key=lambda b: b.id):
            board_channels = [ch for ch in self.lanes.keys() if ch.board == board]
            board_channels.sort(key=lambda c: c.local_id)
            sorted_channels.extend(board_channels)
        
        # 为每个通道生成操作序列
        for channel in sorted_channels:
            lane = self.lanes[channel]
            
            # 构建操作序列字符串
            ops_sequence = []
            for op in lane.operations:
                ops_sequence.append(simplify_operation(op))
            
            # 用箭头连接操作
            sequence_str = " → ".join(ops_sequence)
            
            # 显示通道和序列
            lines.append(f"{str(channel):<20} │ {sequence_str}")
        
        return "\n".join(lines)
    
    def compact_view(self) -> str:
        """紧凑视图：最简洁的表示，适合快速概览"""
        if not self.lanes:
            return "Empty morphism"
        
        # 按板卡分组
        board_parts = []
        for board in sorted(self.boards, key=lambda b: b.id):
            board_channels = [ch for ch in self.lanes.keys() if ch.board == board]
            board_channels.sort(key=lambda c: c.local_id)
            
            channel_parts = []
            for channel in board_channels:
                lane = self.lanes[channel]
                # 统计主要操作类型
                ttl_ops = [op for op in lane.operations if op.operation_type in [OperationType.TTL_INIT, OperationType.TTL_ON, OperationType.TTL_OFF]]
                wait_ops = [op for op in lane.operations if op.operation_type in [OperationType.WAIT, OperationType.WAIT]]
                
                if len(ttl_ops) == 3 and any(op.operation_type == OperationType.TTL_ON for op in ttl_ops):
                    # 识别为脉冲模式
                    pulse_duration = sum(op.duration_us for op in wait_ops if op.operation_type == OperationType.WAIT)
                    channel_parts.append(f"ch{channel.local_id}:pulse({pulse_duration:.1f}μs)")
                else:
                    # 普通操作序列
                    op_count = len([op for op in lane.operations if op.operation_type != OperationType.WAIT])
                    channel_parts.append(f"ch{channel.local_id}:{op_count}ops")
            
            board_parts.append(f"{board.id}[{','.join(channel_parts)}]")
        
        return f"⚡ {' | '.join(board_parts)} ({self.total_duration_us:.1f}μs)"
    
    def compile_to_oasm(self) -> List[OASMCall]:
        """编译当前 Morphism 为 OASM 调用序列
        
        Returns:
            OASMCall 列表，包含 seq(adr, dsl_func, *args, **kwargs) 调用信息
        """
        return compile_to_oasm_calls(self)
    
    def execute_on_hardware(self, seq_object) -> bool:
        """在硬件上执行当前 Morphism
        
        Args:
            seq_object: OASM assembler 序列对象
            
        Returns:
            是否执行成功
        """
        calls = self.compile_to_oasm()
        return execute_oasm_calls(calls, seq_object)
    
    def _append_wait_to_all(self, wait_op: AtomicMorphism, strict: bool) -> 'Morphism':
        """将 wait 操作添加到所有通道"""
        new_lanes = {}
        for channel, lane in self.lanes.items():
            # 为每个通道创建适配的 wait 操作
            adapted_wait = AtomicMorphism(
                channel=channel,
                start_state=lane.end_state,
                end_state=lane.end_state,
                duration_cycles=wait_op.duration_cycles,
                operation_type=OperationType.WAIT
            )
            new_lanes[channel] = Lane(operations=lane.operations + (adapted_wait,))
        return Morphism(lanes=new_lanes)
    
    def _append_to_channel(self, op: AtomicMorphism, strict: bool) -> 'Morphism':
        """将操作追加到指定通道的 Lane"""
        channel = op.channel
        current_lane = self.lanes[channel]
        
        if strict:
            # 严格匹配：状态必须完全相同
            if current_lane.end_state != op.start_state:
                raise ValueError(
                    f"Cannot append with @: channel {channel} ends with {current_lane.end_state}, "
                    f"but {op.operation_type} starts with {op.start_state}"
                )
        else:
            # 自动匹配：只对非 wait 操作验证状态
            if op.operation_type != OperationType.WAIT and current_lane.end_state != op.start_state:
                raise ValueError(
                    f"Cannot append with >>: channel {channel} ends with {current_lane.end_state}, "
                    f"but {op.operation_type} starts with {op.start_state}"
                )
        
        new_lanes = dict(self.lanes)
        new_lanes[channel] = Lane(operations=current_lane.operations + (op,))
        return Morphism(lanes=new_lanes)
    
    def _add_new_channel(self, op: AtomicMorphism) -> 'Morphism':
        """添加新通道的操作"""
        if op.operation_type == OperationType.WAIT:
            raise ValueError("Cannot start new channel with wait operation")
        
        new_lanes = dict(self.lanes)
        new_lanes[op.channel] = Lane(operations=(op,))
        return Morphism(lanes=new_lanes)
    
    def _compose_morphisms(self, other: 'Morphism', strict: bool) -> 'Morphism':
        """Morphism @ Morphism 组合：应用分配律
        
        (A1 | B1) @ (A2 | B2) → (A1@A2) | (B1@B2)
        需要处理时长不匹配的情况，自动插入 wait 操作
        """
        # 1. 时长分析：计算两个 Morphism 的时长差异
        self_duration = self.total_duration_cycles
        other_duration = other.total_duration_cycles
        
        # 2. 获取所有涉及的通道
        all_channels = self.channels | other.channels
        
        # 3. 为每个通道构建组合序列
        new_lanes = {}
        
        for channel in all_channels:
            # 获取该通道在两个 Morphism 中的 Lane（可能为空）
            self_lane = self.lanes.get(channel)
            other_lane = other.lanes.get(channel)
            
            if self_lane is not None and other_lane is not None:
                # 通道在两个 Morphism 中都存在：直接串行组合
                # 验证状态连续性
                if strict and self_lane.end_state != other_lane.start_state:
                    raise ValueError(
                        f"Cannot compose Morphisms with @: channel {channel} "
                        f"ends with {self_lane.end_state} but next starts with {other_lane.start_state}"
                    )
                
                # 组合操作序列
                combined_operations = self_lane.operations + other_lane.operations
                new_lanes[channel] = Lane(operations=combined_operations)
                
            elif self_lane is not None:
                # 通道只在第一个 Morphism 中存在：需要在第二阶段补齐 identity
                padding_cycles = other_duration
                if padding_cycles > 0:
                    identity_op = AtomicMorphism(
                        channel=channel,
                        start_state=self_lane.end_state,
                        end_state=self_lane.end_state,
                        duration_cycles=padding_cycles,
                        operation_type=OperationType.WAIT
                    )
                    combined_operations = self_lane.operations + (identity_op,)
                else:
                    combined_operations = self_lane.operations
                
                new_lanes[channel] = Lane(operations=combined_operations)
                
            elif other_lane is not None:
                # 通道只在第二个 Morphism 中存在：需要在第一阶段补齐 identity
                # 假设初始状态为 UNINITIALIZED（需要初始化）
                padding_cycles = self_duration
                if padding_cycles > 0:
                    # 需要先初始化，然后等待，再执行第二个 Morphism
                    init_op = AtomicMorphism(
                        channel=channel,
                        start_state=TTLState.UNINITIALIZED,
                        end_state=TTLState.OFF,
                        duration_cycles=1,
                        operation_type=OperationType.TTL_INIT
                    )
                    wait_op = AtomicMorphism(
                        channel=channel,
                        start_state=TTLState.OFF,
                        end_state=TTLState.OFF,
                        duration_cycles=padding_cycles - 1,
                        operation_type=OperationType.WAIT
                    )
                    combined_operations = (init_op, wait_op) + other_lane.operations
                else:
                    combined_operations = other_lane.operations
                
                new_lanes[channel] = Lane(operations=combined_operations)
        
        return Morphism(lanes=new_lanes)


def from_atomic(op: AtomicMorphism) -> Morphism:
    """从单个原子操作创建 Morphism"""
    if op.operation_type == OperationType.WAIT:
        raise ValueError("Cannot create Morphism starting with wait operation - channel is undefined")
    
    if op.channel is None:
        raise ValueError("AtomicMorphism must have a channel to create Morphism")
    
    return Morphism(lanes={op.channel: Lane(operations=(op,))})


# === 原子 Morphism ===

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
    
    @property
    def duration_us(self) -> float:
        """获取时长（微秒）"""
        return cycles_to_us(self.duration_cycles)
    
    def with_states(self, start_state: Optional[TTLState], end_state: Optional[TTLState]) -> 'AtomicMorphism':
        """创建带有指定状态的新 AtomicMorphism（用于 wait 操作的状态推导）"""
        return AtomicMorphism(
            channel=self.channel,
            start_state=start_state,
            end_state=end_state,
            duration_cycles=self.duration_cycles,
            operation_type=self.operation_type
        )
    
    def __rshift__(self, other) -> 'Morphism':
        """>> 自动匹配操作符：只支持与 AtomicMorphism 的组合"""
        if isinstance(other, AtomicMorphism):
            return auto_compose(self, other)
        else:
            return NotImplemented
    
    def __matmul__(self, other) -> 'Morphism':
        """@ 严格匹配操作符：只支持与 AtomicMorphism 的组合"""
        if isinstance(other, AtomicMorphism):
            return strict_compose(self, other)
        else:
            return NotImplemented
    
    def __or__(self, other) -> 'Morphism':
        """| 并行组合操作符：支持与 AtomicMorphism 或 Morphism 的组合"""
        if isinstance(other, AtomicMorphism):
            return from_atomic(self) | from_atomic(other)
        elif isinstance(other, Morphism):
            return from_atomic(self) | other
        else:
            return NotImplemented


# === 具体的原子操作 ===

def ttl_init(channel: Channel) -> AtomicMorphism:
    """初始化TTL通道：UNINITIALIZED → OFF"""
    return AtomicMorphism(
        channel=channel,
        start_state=TTLState.UNINITIALIZED,
        end_state=TTLState.OFF,
        duration_cycles=1,  # 1个时钟周期
        operation_type=OperationType.TTL_INIT
    )


def ttl_on(channel: Channel) -> AtomicMorphism:
    """开启TTL通道：OFF → ON"""
    return AtomicMorphism(
        channel=channel,
        start_state=TTLState.OFF,
        end_state=TTLState.ON,
        duration_cycles=1,  # 1个时钟周期
        operation_type=OperationType.TTL_ON
    )


def ttl_off(channel: Channel) -> AtomicMorphism:
    """关闭TTL通道：ON → OFF"""
    return AtomicMorphism(
        channel=channel,
        start_state=TTLState.ON,
        end_state=TTLState.OFF,
        duration_cycles=1,  # 1个时钟周期
        operation_type=OperationType.TTL_OFF
    )


def wait(duration_us: float) -> AtomicMorphism:
    """等待操作：保持当前所有状态"""
    return AtomicMorphism(
        channel=None,  # 不涉及特定通道
        start_state=None,  # 在组合时确定
        end_state=None,    # 在组合时确定
        duration_cycles=us_to_cycles(duration_us),
        operation_type=OperationType.WAIT
    )


# === 组合逻辑 ===

def strict_compose(first: AtomicMorphism, second: AtomicMorphism) -> Morphism:
    """严格匹配的组合操作 (@)
    
    要求两个 Morphism 的状态完全匹配：
    - first.end_state 必须等于 second.start_state
    - 不允许任何状态推导或适配
    """
    if first.end_state != second.start_state:
        raise ValueError(
            f"Cannot compose with @: {first.operation_type} ends with {first.end_state}, "
            f"but {second.operation_type} starts with {second.start_state}. "
            f"States must match exactly for @ composition."
        )
    
    # 创建包含两个操作的 Morphism
    if first.channel is None or second.channel is None:
        raise ValueError("Cannot compose AtomicMorphisms with undefined channels")
    
    if first.channel != second.channel:
        raise ValueError(f"Cannot compose operations on different channels: {first.channel} vs {second.channel}")
    
    # 创建 Lane 包含两个操作序列
    lane = Lane(operations=(first, second))
    return Morphism(lanes={first.channel: lane})


def auto_compose(first: AtomicMorphism, second: AtomicMorphism) -> Morphism:
    """自动匹配的组合操作 (>>)
    
    - 对 wait 操作：自动推导状态
    - 对其他操作：允许匹配的状态，拒绝不匹配的状态
    """
    
    # 如果第二个是 wait 操作，自动推导其状态
    if second.operation_type == OperationType.WAIT:
        adapted_second = second.with_states(
            start_state=first.end_state,
            end_state=first.end_state  # wait 保持状态不变
        )
        # wait 操作需要指定通道
        adapted_second = AtomicMorphism(
            channel=first.channel,
            start_state=first.end_state,
            end_state=first.end_state,
            duration_cycles=second.duration_cycles,
            operation_type=OperationType.WAIT
        )
    else:
        # 非 wait 操作保持原状态
        adapted_second = second
    
    # 验证最终状态匹配
    if first.end_state != adapted_second.start_state:
        raise ValueError(
            f"Cannot auto-compose with >>: {first.operation_type} ends with {first.end_state}, "
            f"but {adapted_second.operation_type} starts with {adapted_second.start_state}. "
            f"States must match for >> composition."
        )
    
    # 创建包含两个操作的 Morphism
    if first.channel is None:
        raise ValueError("Cannot compose AtomicMorphism with undefined channel")
    
    if adapted_second.channel is None:
        raise ValueError("Cannot compose AtomicMorphism with undefined channel")
        
    if first.channel != adapted_second.channel:
        raise ValueError(f"Cannot compose operations on different channels: {first.channel} vs {adapted_second.channel}")
    
    # 创建 Lane 包含两个操作序列
    lane = Lane(operations=(first, adapted_second))
    return Morphism(lanes={first.channel: lane})


if __name__ == "__main__":
    # 测试用户的原始工作版本
    rwg0 = Board('RWG_0')
    cooling_laser_sw = Channel(rwg0, 0)
    repump_laser_sw = Channel(rwg0, 1) 
    imaging_laser_sw = Channel(rwg0, 2)

    print('=== 用户的原始工作版本测试 ===')
    init_all = ttl_init(cooling_laser_sw) | ttl_init(repump_laser_sw) | ttl_init(imaging_laser_sw)
    pulse1 = from_atomic(ttl_on(cooling_laser_sw)) >> wait(10.0) >> ttl_off(cooling_laser_sw)
    pulse2 = from_atomic(ttl_on(repump_laser_sw)) >> wait(10.0) >> ttl_off(repump_laser_sw)

    print('States check:')
    combined_pulses = pulse1 | pulse2
    print('init_all end states:', {str(ch): lane.end_state for ch, lane in init_all.lanes.items()})
    print('combined_pulses start states:', {str(ch): lane.start_state for ch, lane in combined_pulses.lanes.items()})

    print('\nTrying composition...')
    try:
        seq = init_all @ combined_pulses
        print('✅ SUCCESS!')
        print('Result:', seq.compact_view())
        print('\nDetailed view:')
        print(seq.lanes_view())
        
        print('\n=== OASM 编译演示 ===')
        oasm_calls = seq.compile_to_oasm()
        print(f'生成了 {len(oasm_calls)} 个 OASM 调用:')
        print('-' * 50)
        for i, call in enumerate(oasm_calls):
            args_str = ', '.join(str(arg) for arg in call.args) if call.args else ''
            kwargs_str = ', '.join(f'{k}={v}' for k, v in call.kwargs.items()) if call.kwargs else ''
            params_str = ', '.join(filter(None, [args_str, kwargs_str]))
            
            func_name = call.dsl_func.__name__ if hasattr(call.dsl_func, '__name__') else str(call.dsl_func)
            print(f'{i+1:2d}. seq(\'{call.adr.value}\', {func_name}, {params_str})')
        print('-' * 50)
        
        print('\n=== 用户可以这样使用 ===')
        print('# 创建 assembler 序列对象')
        print('seq = assembler(run_all, [(\'rwg0\', rwg.C_RWG), (\'main\', C_MAIN)])')
        print('# 执行编译好的调用')
        for call in oasm_calls[:3]:  # 只显示前3个作为示例
            args_str = ', '.join(str(arg) for arg in call.args) if call.args else ''
            kwargs_str = ', '.join(f'{k}={v}' for k, v in call.kwargs.items()) if call.kwargs else ''
            params_str = ', '.join(filter(None, [args_str, kwargs_str]))
            func_name = call.dsl_func.__name__ if hasattr(call.dsl_func, '__name__') else str(call.dsl_func)
            print(f'seq(\'{call.adr.value}\', {func_name}, {params_str})')
        if len(oasm_calls) > 3:
            print(f'# ... 还有 {len(oasm_calls) - 3} 个调用')
        print('seq.run()')
            
    except Exception as e:
        print('❌ FAILED:', str(e))
