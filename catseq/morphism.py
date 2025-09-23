"""
Morphism class and composition operations.

This module implements the core Morphism class with composition operators
and state inference logic for building complex quantum control sequences.
"""

from dataclasses import dataclass
from typing import Dict, Callable, List, Self


from .lanes import Lane
from .time_utils import cycles_to_us, us_to_cycles, time_to_cycles, cycles_to_time
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
        # Allow composing with raw AtomicMorphisms for convenience
        if isinstance(other, AtomicMorphism):
            other = from_atomic(other)

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
        
        # Case 3: Morphism >> MorphismDef (apply MorphismDef to all channels)
        elif isinstance(other, MorphismDef):
            return other(self)  # Use the multi-channel call functionality
        
        # Case 4: Morphism >> Dict[Channel, MorphismDef] (apply different operations to different channels)
        elif isinstance(other, dict):
            # Type check: all keys must be Channels, all values must be MorphismDefs
            if not all(isinstance(k, Channel) for k in other.keys()):
                return NotImplemented
            if not all(isinstance(v, MorphismDef) for v in other.values()):
                return NotImplemented
            return self._apply_channel_operations(other)

        # Case 5: Unsupported type
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
            
            # 尝试识别脉冲模式
            pulse_pattern = self._detect_pulse_pattern(lane)
            if pulse_pattern:
                line = f"{channel.global_id:<20} │ {pulse_pattern}"
            else:
                # 详细模式：显示所有操作和状态
                ops_display = []
                for i, op in enumerate(lane.operations):
                    op_str = self._format_operation_with_state(op, show_state=(i == 0 or i == len(lane.operations) - 1))
                    ops_display.append(op_str)
                
                line = f"{channel.global_id:<20} │ {' → '.join(ops_display)}"
            
            lines.append(line)
        
        return "\n".join(lines)
    
    def _detect_pulse_pattern(self, lane: "Lane") -> str | None:
        """检测常见的脉冲模式"""
        ops = lane.operations
        
        # TTL pulse: ttl_on → wait → ttl_off
        if (len(ops) == 3 and 
            ops[0].operation_type == OperationType.TTL_ON and
            ops[1].operation_type == OperationType.IDENTITY and
            ops[2].operation_type == OperationType.TTL_OFF):
            duration = cycles_to_us(ops[1].duration_cycles)
            return f"🔲 TTL_pulse({duration:.1f}μs)"
        
        # RF pulse: rf_switch(on) → wait → rf_switch(off)
        if (len(ops) == 3 and 
            ops[0].operation_type == OperationType.RWG_RF_SWITCH and
            ops[1].operation_type == OperationType.IDENTITY and
            ops[2].operation_type == OperationType.RWG_RF_SWITCH):
            # 检查是否是 False → True → False 的 RF 状态变化
            if (hasattr(ops[0].start_state, 'rf_on') and hasattr(ops[0].end_state, 'rf_on') and
                hasattr(ops[2].start_state, 'rf_on') and hasattr(ops[2].end_state, 'rf_on')):
                if (ops[0].start_state.rf_on == False and ops[0].end_state.rf_on == True and
                    ops[2].start_state.rf_on == True and ops[2].end_state.rf_on == False):
                    duration = cycles_to_us(ops[1].duration_cycles)
                    return f"📡 RF_pulse({duration:.1f}μs)"
        
        return None
    
    def _format_operation_with_state(self, op: "AtomicMorphism", show_state: bool = False) -> str:
        """格式化操作显示，可选地显示状态信息"""
        from .time_utils import cycles_to_us
        
        duration_us = cycles_to_us(op.duration_cycles)
        op_name = {
            OperationType.TTL_INIT: "init",
            OperationType.TTL_ON: "ON", 
            OperationType.TTL_OFF: "OFF",
            OperationType.RWG_INIT: "init",
            OperationType.RWG_SET_CARRIER: "set_carrier",
            OperationType.RWG_LOAD_COEFFS: "load",
            OperationType.RWG_UPDATE_PARAMS: "play",
            OperationType.RWG_RF_SWITCH: "rf_switch",
            OperationType.IDENTITY: "wait",
            OperationType.SYNC_MASTER: "sync_master",
            OperationType.SYNC_SLAVE: "sync_slave",
        }.get(op.operation_type, str(op.operation_type))
        
        if duration_us > 0:
            op_display = f"{op_name}({duration_us:.1f}μs)"
        else:
            op_display = op_name
        
        # 添加状态信息（如果需要且可用）
        if show_state and hasattr(op.end_state, 'rf_on'):
            rf_status = "RF_ON" if op.end_state.rf_on else "RF_OFF"
            op_display += f"[{rf_status}]"
        elif show_state and op.end_state and hasattr(op.end_state, 'name'):
            op_display += f"[{op.end_state.name}]"
        
        return op_display

    def timeline_view(self, compact: bool = True) -> str:
        """生成时间轴视图，显示并行操作的时序关系
        
        Args:
            compact: 是否使用紧凑模式（不按比例显示等待时间）
        """
        if not self.lanes:
            if self.total_duration_cycles > 0:
                return f"Identity Morphism ({self.total_duration_us:.1f}μs)"
            return "Empty Morphism"
        
        lines = []
        lines.append(f"Timeline View ({self.total_duration_us:.1f}μs):")
        lines.append("=" * 80)
        
        if compact:
            return self._generate_compact_timeline(lines)
        else:
            return self._generate_proportional_timeline(lines)
    
    def _generate_compact_timeline(self, lines: list) -> str:
        """生成紧凑时间轴：事件驱动，不按比例显示等待"""
        # 收集所有时间点事件
        events = []
        sorted_channels = sorted(self.lanes.keys(), key=lambda ch: (ch.board.id, ch.local_id))
        
        for channel in sorted_channels:
            lane = self.lanes[channel]
            current_time = 0.0
            
            for op in lane.operations:
                if op.operation_type != OperationType.IDENTITY:
                    # 记录非等待操作
                    events.append({
                        'time': current_time,
                        'channel': channel,
                        'operation': op,
                        'type': 'instant'
                    })
                else:
                    # 记录等待区间
                    wait_duration = cycles_to_us(op.duration_cycles)
                    events.append({
                        'time': current_time,
                        'channel': channel,
                        'operation': op,
                        'duration': wait_duration,
                        'type': 'wait'
                    })
                
                current_time += cycles_to_us(op.duration_cycles)
        
        # 按时间排序事件
        events.sort(key=lambda e: (e['time'], e['channel'].global_id))
        
        # 生成时间点标记
        unique_times = sorted(set(e['time'] for e in events))
        time_markers = []
        for t in unique_times[:10]:  # 最多显示10个时间点
            time_markers.append(self._format_time(t))
        
        lines.append("Events: " + " → ".join(time_markers))
        lines.append("")
        
        # 为每个通道生成事件序列
        for channel in sorted_channels:
            channel_events = [e for e in events if e['channel'] == channel]
            timeline_parts = []
            
            for event in channel_events:
                if event['type'] == 'instant':
                    # 瞬时操作
                    symbol = self._get_operation_symbol(event['operation'])
                    timeline_parts.append(f"t={self._format_time(event['time'])}:{symbol}")
                else:
                    # 等待操作，显示为压缩形式
                    duration = event['duration']
                    if duration > 0.1:  # 只显示有意义的等待
                        timeline_parts.append(f"⏳({self._format_time(duration)})")
            
            if timeline_parts:
                timeline = " → ".join(timeline_parts)
                lines.append(f"{channel.global_id:<9} │ {timeline}")
        
        return "\n".join(lines)
    
    def _generate_proportional_timeline(self, lines: list) -> str:
        """生成按比例的时间轴（传统方式，但有合理限制）"""
        total_us = self.total_duration_us
        max_chars = 100
        
        # 自适应分辨率
        if total_us <= 100:  # < 100μs
            resolution_us = 1.0
            chars_per_us = min(1, max_chars / total_us)
        elif total_us <= 1000:  # < 1ms
            resolution_us = 10.0
            chars_per_us = 0.1
        else:  # >= 1ms，使用压缩显示
            resolution_us = total_us / max_chars
            chars_per_us = 1.0 / resolution_us
        
        # 生成时间标尺
        time_steps = int(total_us / resolution_us)
        if time_steps > max_chars:
            return self._generate_compact_timeline(lines)
        
        time_markers = []
        for i in range(0, min(time_steps, 10)):
            marker_time = i * resolution_us
            time_markers.append(self._format_time(marker_time))
        
        lines.append("Time: " + " ".join(f"{marker:>8}" for marker in time_markers))
        lines.append(" " * 6 + "─" * min(time_steps, max_chars))
        
        # 生成通道时间线
        sorted_channels = sorted(self.lanes.keys(), key=lambda ch: (ch.board.id, ch.local_id))
        
        for channel in sorted_channels:
            lane = self.lanes[channel]
            timeline = self._generate_channel_timeline_proportional(
                lane, total_us, resolution_us, max_chars
            )
            lines.append(f"{channel.global_id:<9} │{timeline}")
        
        return "\n".join(lines)
    
    def _get_operation_symbol(self, op: "AtomicMorphism") -> str:
        """获取操作的符号表示"""
        symbol_map = {
            OperationType.TTL_ON: "▲",
            OperationType.TTL_OFF: "▼",  
            OperationType.TTL_INIT: "◇",
            OperationType.RWG_INIT: "◆",
            OperationType.RWG_SET_CARRIER: "🔶",
            OperationType.RWG_LOAD_COEFFS: "📥",
            OperationType.RWG_UPDATE_PARAMS: "▶️",
            OperationType.SYNC_MASTER: "🔄",
            OperationType.SYNC_SLAVE: "🔃",
        }
        
        if op.operation_type == OperationType.RWG_RF_SWITCH:
            if hasattr(op.end_state, 'rf_on') and op.end_state.rf_on:
                return "📡"  # RF ON
            else:
                return "📴"  # RF OFF
        
        return symbol_map.get(op.operation_type, "●")
    
    def _format_time(self, time_us: float) -> str:
        """格式化时间显示"""
        if time_us < 1:
            return f"{time_us:.1f}μs"
        elif time_us < 1000:
            return f"{time_us:.0f}μs"
        elif time_us < 1000000:
            return f"{time_us/1000:.1f}ms"
        else:
            return f"{time_us/1000000:.1f}s"
    
    def _generate_channel_timeline(self, lane: "Lane", total_us: float, resolution_us: float) -> str:
        """为单个通道生成时间线字符串"""
        timeline_length = max(1, int(total_us / resolution_us)) * 8  # 8 chars per time step
        timeline = [' '] * timeline_length
        
        current_time_us = 0.0
        for op in lane.operations:
            op_duration_us = cycles_to_us(op.duration_cycles)
            start_pos = int(current_time_us / resolution_us) * 8
            end_pos = int((current_time_us + op_duration_us) / resolution_us) * 8
            
            # 选择表示符号
            if op.operation_type == OperationType.TTL_ON:
                symbol = '▲'
            elif op.operation_type == OperationType.TTL_OFF:
                symbol = '▼'
            elif op.operation_type == OperationType.RWG_RF_SWITCH:
                if hasattr(op.end_state, 'rf_on') and op.end_state.rf_on:
                    symbol = '◆'  # RF ON
                else:
                    symbol = '◇'  # RF OFF
            elif op.operation_type == OperationType.IDENTITY:
                symbol = '─'
            else:
                symbol = '●'
            
            # 填充时间线
            if op.operation_type == OperationType.IDENTITY:
                # 等待操作显示为连续线
                for pos in range(start_pos, min(end_pos, timeline_length)):
                    timeline[pos] = symbol
            else:
                # 瞬时操作显示为单个符号
                if start_pos < timeline_length:
                    timeline[start_pos] = symbol
            
            current_time_us += op_duration_us
        
        return ''.join(timeline)

    def _apply_channel_operations(self, channel_operations: Dict[Channel, 'MorphismDef']) -> 'Morphism':
        """Apply different operations to different channels with automatic time alignment.
        
        Args:
            channel_operations: Dictionary mapping channels to their operations
            
        Returns:
            New Morphism with all operations applied and time-aligned
            
        Raises:
            ValueError: If any channel in the dictionary is not found in this morphism
        """
        # 1. Validate that all channels exist in the morphism
        for channel in channel_operations.keys():
            if channel not in self.lanes:
                available_channels = [str(ch.global_id) for ch in self.lanes.keys()]
                raise ValueError(
                    f"Channel {channel.global_id} not found in morphism. "
                    f"Available channels: {available_channels}"
                )
        
        # Handle empty dictionary case
        if not channel_operations:
            return self
        
        # 2. Execute all specified operations and track maximum duration
        operation_results = {}
        max_duration_cycles = 0
        
        for channel, operation_def in channel_operations.items():
            # Get the end state of this channel
            lane = self.lanes[channel]
            if lane.operations:
                end_state = lane.operations[-1].end_state
            else:
                end_state = RWGUninitialized()
            
            # Execute the operation
            result_morphism = operation_def(channel, end_state)
            operation_results[channel] = result_morphism
            
            # Track maximum duration
            operation_duration = result_morphism.total_duration_cycles
            max_duration_cycles = max(max_duration_cycles, operation_duration)
        
        # 3. Time alignment: pad shorter operations to match the longest
        aligned_results = {}
        
        for channel, result_morphism in operation_results.items():
            current_duration = result_morphism.total_duration_cycles
            
            if current_duration < max_duration_cycles:
                # Need to pad with identity operation
                padding_cycles = max_duration_cycles - current_duration
                
                if padding_cycles > 0:
                    # Get the end state to create identity operation
                    if channel in result_morphism.lanes:
                        channel_lane = result_morphism.lanes[channel]
                        end_state = channel_lane.operations[-1].end_state if channel_lane.operations else RWGUninitialized()
                        
                        # Create identity operation manually
                        padding_op = AtomicMorphism(
                            channel=channel,
                            start_state=end_state,
                            end_state=end_state,
                            duration_cycles=padding_cycles,
                            operation_type=OperationType.IDENTITY
                        )
                        
                        # Add padding operation to the existing operations
                        padded_operations = channel_lane.operations + (padding_op,)
                        aligned_results[channel] = Morphism({channel: Lane(padded_operations)})
                    else:
                        # This should not happen, but handle gracefully
                        aligned_results[channel] = result_morphism
                else:
                    aligned_results[channel] = result_morphism
            else:
                # Already at maximum duration
                aligned_results[channel] = result_morphism
        
        # 4. Build new lanes
        new_lanes = {}
        
        for channel, lane in self.lanes.items():
            if channel in aligned_results:
                # Use the aligned operation result
                aligned_morphism = aligned_results[channel]
                new_operations = lane.operations + aligned_morphism.lanes[channel].operations
                new_lanes[channel] = Lane(new_operations)
            else:
                # Channel not specified in dictionary - add wait operation
                if lane.operations:
                    end_state = lane.operations[-1].end_state
                else:
                    end_state = RWGUninitialized()
                
                # Create identity operation for the maximum duration
                wait_operation = AtomicMorphism(
                    channel=channel,
                    start_state=end_state,
                    end_state=end_state,
                    duration_cycles=max_duration_cycles,
                    operation_type=OperationType.IDENTITY
                )
                
                new_operations = lane.operations + (wait_operation,)
                new_lanes[channel] = Lane(new_operations)
        
        return Morphism(new_lanes)


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

def identity(duration: float) -> "Morphism":
    """Creates a channelless identity morphism (a pure wait).

    Args:
        duration: Wait time in seconds (SI unit)
    """
    duration_cycles = time_to_cycles(duration)
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
        padding_seconds = cycles_to_time(padding_cycles)
        # identity() returns a channelless Morphism, >> will broadcast it
        left = left >> identity(padding_seconds)
    elif right_duration < left_duration:
        padding_cycles = left_duration - right_duration
        padding_seconds = cycles_to_time(padding_cycles)
        # identity() returns a channelless Morphism, >> will broadcast it
        right = right >> identity(padding_seconds)

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

    def __call__(self, target: "Channel | Morphism", start_state: "State | None" = None) -> "Morphism":
        """Executes the generator to produce a concrete Morphism.
        
        Args:
            target: Either a Channel (single-channel mode) or a Morphism (multi-channel mode)
            start_state: Starting state (only used in single-channel mode)
        """
        if isinstance(target, Channel):
            # Single-channel mode: existing behavior
            if start_state is None:
                start_state = RWGUninitialized() # Default start for RWG
            return self._generator(target, start_state)
        else:
            # Multi-channel mode: apply this MorphismDef to all channels in the target Morphism
            if not hasattr(target, 'lanes'):
                raise TypeError(f"Target must be Channel or Morphism, got {type(target)}")
            
            new_lanes = {}
            for channel, lane in target.lanes.items():
                # Get the end state of this channel from its last operation
                if lane.operations:
                    end_state = lane.operations[-1].end_state
                else:
                    end_state = RWGUninitialized()
                
                # Apply this MorphismDef to this channel
                morphism_piece = self._generator(channel, end_state)
                
                # Extend existing lane with new operations
                new_operations = lane.operations + morphism_piece.lanes[channel].operations
                new_lanes[channel] = Lane(new_operations)
                
            return Morphism(lanes=new_lanes)

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
            start_state = RWGUninitialized()

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