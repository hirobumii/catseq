"""
Standalone and testable script for Morphism timeline visualization.

This file contains all necessary mock objects and the core visualization logic
to produce a timeline plot from a Morphism object. It is designed to be
run directly for testing and validation.
"""

import matplotlib.pyplot as plt
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict

# Assume these are correctly imported from your project structure
from ..morphism import Morphism
from ..lanes import merge_board_lanes, PhysicalLane, PhysicalOperation
from ..time_utils import cycles_to_us
from ..types import Board, Channel, OperationType


# ==============================================================================
# CORE VISUALIZATION LOGIC (Refactored and Cleaned)
# ==============================================================================

def plot_timeline(morphism: Morphism,
                  figsize: Tuple[int, int] = (15, 8),
                  filename: Optional[str] = None,
                  show_sync: bool = True,
                  **kwargs) -> Tuple[plt.Figure, plt.Axes]:
    """使用 matplotlib 绘制时间轴"""
    physical_lanes = _compute_physical_lanes(morphism)

    # FIX: Calculate duration into a local variable instead of modifying the morphism object.
    # Start with the original duration and update if there are operations.
    calculated_duration = getattr(morphism, 'total_duration_us', 0.0)
    all_pops = [pop for lane in physical_lanes.values() for pop in lane.operations]
    if all_pops:
        calculated_duration = max(pop.timestamp_us + cycles_to_us(pop.operation.duration_cycles) for pop in all_pops)

    if not physical_lanes:
        fig, ax = plt.subplots(figsize=figsize)
        # Use the original duration since there's nothing to calculate
        duration = getattr(morphism, 'total_duration_us', 0.0)
        ax.text(0.5, 0.5, f'Empty Morphism\nDuration: {duration:.1f}μs',
                ha='center', va='center', transform=ax.transAxes)
        return fig, ax

    fig, ax = plt.subplots(figsize=figsize)

    _plot_adaptive_timeline(ax, physical_lanes, **kwargs)

    if show_sync:
        sync_points = _detect_sync_points(physical_lanes)
        time_mapping = _get_adaptive_time_mapping(physical_lanes)
        _draw_sync_markers(ax, sync_points, time_mapping=time_mapping)
        
    # FIX: Pass the locally calculated duration to the aesthetics setup function.
    _setup_plot_aesthetics(ax, calculated_duration)

    if filename:
        fig.savefig(filename, dpi=300, bbox_inches='tight')
        print(f"Timeline plot saved to {filename}")

    return fig, ax

def text_timeline(morphism: Morphism, max_width: int = 100) -> str:
    """生成文本形式的时间轴"""
    if not morphism.lanes:
        return f"Empty Morphism (0.0μs)"
    physical_lanes = _compute_physical_lanes(morphism)
    return _generate_text_timeline(physical_lanes, max_width)

def _compute_physical_lanes(morphism: Morphism) -> Dict[Board, PhysicalLane]:
    """使用编译器组件计算物理时间线"""
    boards_lanes_data = morphism.lanes_by_board()
    return {
        board: merge_board_lanes(board, board_lanes)
        for board, board_lanes in boards_lanes_data.items()
    }

def _group_by_channel(operations: List[PhysicalOperation]) -> Dict[Channel, List[PhysicalOperation]]:
    """按通道分组物理操作"""
    channel_ops = defaultdict(list)
    for pop in operations:
        channel_ops[pop.operation.channel].append(pop)
    
    for ops in channel_ops.values():
        ops.sort(key=lambda x: x.timestamp_cycles)
    
    return channel_ops

def _detect_pulse_patterns(ops: List[PhysicalOperation]) -> List[Dict[str, Any]]:
    """检测单个通道的脉冲模式"""
    patterns = []
    i = 0
    while i < len(ops) - 1:
        current_op, next_op = ops[i], ops[i+1]
        
        # TTL Pulse
        if (current_op.operation.operation_type == OperationType.TTL_ON and
            next_op.operation.operation_type == OperationType.TTL_OFF):
            patterns.append({
                'type': 'TTL_PULSE', 'start_time': current_op.timestamp_us,
                'duration': next_op.timestamp_us - current_op.timestamp_us,
                'operation_indices': {i, i + 1}
            })
            i += 2
            continue

        # RF Pulse
        if (current_op.operation.operation_type == OperationType.RWG_RF_SWITCH and
            next_op.operation.operation_type == OperationType.RWG_RF_SWITCH and
            hasattr(current_op.operation, 'end_state') and hasattr(next_op.operation, 'end_state') and
            current_op.operation.end_state.rf_on and
            not next_op.operation.end_state.rf_on):
            patterns.append({
                'type': 'RF_PULSE', 'start_time': current_op.timestamp_us,
                'duration': next_op.timestamp_us - current_op.timestamp_us,
                'operation_indices': {i, i + 1}
            })
            i += 2
            continue
        i += 1
    return patterns

def _collect_all_event_times(physical_lanes: Dict[Board, PhysicalLane]) -> List[float]:
    """收集所有关键时间点（操作开始和结束）"""
    time_points = {0.0}
    for lane in physical_lanes.values():
        for pop in lane.operations:
            time_points.add(pop.timestamp_us)
            end_time = pop.timestamp_us + cycles_to_us(pop.operation.duration_cycles)
            time_points.add(end_time)
    return sorted(list(time_points))

def _create_adaptive_time_mapping(event_times: List[float]) -> Dict[float, float]:
    """创建自适应时间映射：真实时间 -> 显示位置"""
    if len(event_times) <= 1:
        return {t: t for t in event_times}
    
    time_mapping = {}
    current_display_pos = 0.0
    min_segment_width = 1.0
    max_segment_width = 10.0
    
    for i, time_point in enumerate(event_times):
        time_mapping[time_point] = current_display_pos
        if i < len(event_times) - 1:
            time_diff = event_times[i + 1] - time_point
            if time_diff == 0:
                continue
            elif time_diff < 1.0:
                display_width = max(min_segment_width, time_diff * 2)
            elif time_diff > 100.0:
                display_width = min(max_segment_width, 2 + time_diff / 50)
            else:
                display_width = min_segment_width + (time_diff / 100.0) * (max_segment_width - min_segment_width)
            current_display_pos += display_width
            
    return time_mapping

def _map_time_to_display(time_us: float, time_mapping: Dict[float, float]) -> float:
    """将真实时间通过线性插值映射到显示位置"""
    sorted_times = sorted(time_mapping.keys())
    if not sorted_times: return 0.0
    if time_us <= sorted_times[0]: return time_mapping[sorted_times[0]]
    if time_us >= sorted_times[-1]: return time_mapping[sorted_times[-1]]
    
    for i in range(len(sorted_times) - 1):
        t1, t2 = sorted_times[i], sorted_times[i + 1]
        if t1 <= time_us <= t2:
            ratio = (time_us - t1) / (t2 - t1) if t2 > t1 else 0
            return time_mapping[t1] + ratio * (time_mapping[t2] - time_mapping[t1])
    return time_mapping[sorted_times[-1]]

def _draw_adaptive_channel_operations(ax: plt.Axes, ops: List[PhysicalOperation], 
                                      y_pos: int, time_mapping: Dict[float, float]):
    """使用自适应时间映射绘制通道操作"""
    pulse_patterns = _detect_pulse_patterns(ops)
    drawn_op_indices = set()
    for p in pulse_patterns:
        drawn_op_indices.update(p['operation_indices'])

    # 绘制脉冲
    for pattern in pulse_patterns:
        start_display = _map_time_to_display(pattern['start_time'], time_mapping)
        end_display = _map_time_to_display(pattern['start_time'] + pattern['duration'], time_mapping)
        width = max(0.5, end_display - start_display)
        
        color, label_prefix = ('lightgreen', 'TTL') if pattern['type'] == 'TTL_PULSE' else ('orange', 'RF')
        label = f"{label_prefix}({pattern['duration']:.1f}μs)"
        
        rect = plt.Rectangle((start_display, y_pos - 0.4), width, 0.8,
                             facecolor=color, alpha=0.7, edgecolor='black', linewidth=1)
        ax.add_patch(rect)
        ax.text(start_display + width/2, y_pos, label, ha='center', va='center', fontsize=8, fontweight='bold')

    # 绘制其他单独操作
    for i, pop in enumerate(ops):
        if i in drawn_op_indices:
            continue
        display_pos = _map_time_to_display(pop.timestamp_us, time_mapping)
        op_type = pop.operation.operation_type
        color = _get_operation_color(op_type)
        symbol = _get_operation_symbol_text(op_type)
        
        ax.plot([display_pos, display_pos], [y_pos-0.4, y_pos+0.4], color=color, linewidth=2)
        ax.text(display_pos, y_pos + 0.2, symbol, ha='center', va='bottom', fontsize=7, rotation=90)

def _get_operation_color(op_type: OperationType) -> str:
    return {
        OperationType.TTL_ON: 'green', OperationType.TTL_OFF: 'red', OperationType.TTL_INIT: 'blue',
        OperationType.RWG_RF_SWITCH: 'orange', OperationType.RWG_INIT: 'purple',
        OperationType.RWG_SET_CARRIER: 'brown', OperationType.RWG_LOAD_COEFFS: 'pink',
        OperationType.RWG_UPDATE_PARAMS: 'olive', OperationType.IDENTITY: 'lightgray',
        OperationType.SYNC_MASTER: 'darkblue', OperationType.SYNC_SLAVE: 'darkgreen',
    }.get(op_type, 'gray')

def _get_operation_symbol_text(op_type: OperationType) -> str:
    return {
        OperationType.TTL_ON: "ON", OperationType.TTL_OFF: "OFF", OperationType.TTL_INIT: "INIT",
        OperationType.RWG_INIT: "INIT", OperationType.RWG_SET_CARRIER: "CARR",
        OperationType.RWG_LOAD_COEFFS: "LOAD", OperationType.RWG_UPDATE_PARAMS: "PLAY",
        OperationType.RWG_RF_SWITCH: "RF", OperationType.SYNC_MASTER: "SYNC",
        OperationType.SYNC_SLAVE: "SYNC",
    }.get(op_type, "OP")

def _setup_adaptive_time_ticks(ax: plt.Axes, event_times: List[float], time_mapping: Dict[float, float]):
    """设置自适应时间轴刻度"""
    important_times, display_positions = [], []
    if not event_times: return
    
    important_times.append(event_times[0])
    display_positions.append(time_mapping.get(event_times[0], 0.0))
    last_display_pos = display_positions[0]
    
    total_display_width = max(time_mapping.values()) - min(time_mapping.values())
    min_tick_spacing = total_display_width / 15.0 if total_display_width > 0 else 1.0


    for time_point in event_times[1:]:
        display_pos = time_mapping[time_point]
        if display_pos - last_display_pos >= min_tick_spacing:
            important_times.append(time_point)
            display_positions.append(display_pos)
            last_display_pos = display_pos
            
    # Ensure last time point is a tick if it's not too close to the previous one
    if event_times[-1] not in important_times:
        if not display_positions or time_mapping[event_times[-1]] - display_positions[-1] > min_tick_spacing / 2:
            important_times.append(event_times[-1])
            display_positions.append(time_mapping[event_times[-1]])

    ax.set_xticks(display_positions)
    ax.set_xticklabels([f"{t:.1f}" for t in important_times], rotation=45, ha="right")
    ax.set_xlabel("Time (μs) - Adaptive Scale")

def _plot_adaptive_timeline(ax: plt.Axes, physical_lanes: Dict[Board, PhysicalLane], **kwargs):
    """绘制自适应时间尺度的图表"""
    event_times = _collect_all_event_times(physical_lanes)
    time_mapping = _create_adaptive_time_mapping(event_times)
    
    all_ops = [op for lane in physical_lanes.values() for op in lane.operations]
    ops_by_channel = _group_by_channel(all_ops)
    sorted_channels = sorted(ops_by_channel.keys(), key=lambda ch: (ch.board.id, ch.channel_type.name, ch.local_id))

    for y_pos, channel in enumerate(sorted_channels):
        ops = ops_by_channel[channel]
        _draw_adaptive_channel_operations(ax, ops, y_pos, time_mapping)
    
    ax.set_yticks(range(len(sorted_channels)))
    ax.set_yticklabels([ch.global_id for ch in sorted_channels])
    ax.set_ylim(-0.5, len(sorted_channels) - 0.5)
    _setup_adaptive_time_ticks(ax, event_times, time_mapping)

def _get_adaptive_time_mapping(physical_lanes: Dict[Board, PhysicalLane]) -> Dict[float, float]:
    """Helper to get the time mapping for other functions."""
    event_times = _collect_all_event_times(physical_lanes)
    return _create_adaptive_time_mapping(event_times)
    
def _detect_sync_points(physical_lanes: Dict[Board, PhysicalLane]) -> List[Dict[str, Any]]:
    """检测同步点"""
    timestamp_to_ops = defaultdict(list)
    for lane in physical_lanes.values():
        for pop in lane.operations:
            timestamp_to_ops[pop.timestamp_cycles].append(pop)
    
    return [{'time_us': cycles_to_us(ts), 'ops': ops} for ts, ops in timestamp_to_ops.items() if len(ops) > 1]

def _draw_sync_markers(ax: plt.Axes, sync_points: List[Dict[str, Any]], time_mapping: Dict[float, float]):
    """绘制同步标记"""
    for i, sp in enumerate(sync_points):
        time_us = sp['time_us']
        display_pos = _map_time_to_display(time_us, time_mapping)
        ax.axvline(x=display_pos, color='red', linestyle='--', alpha=0.7, linewidth=1.5)
        ax.text(display_pos, ax.get_ylim()[1], f" S{i+1}", ha='center', va='bottom', color='red', fontsize=9)

def _setup_plot_aesthetics(ax: plt.Axes, total_duration_us: float):
    """设置图表美学属性"""
    ax.set_title(f'Morphism Timeline (Total Duration: {total_duration_us:.1f}μs)')
    ax.grid(True, which='major', axis='x', linestyle='--', linewidth=0.5)
    ax.grid(True, which='major', axis='y', linestyle='-', linewidth=0.5)
    ax.invert_yaxis() # Puts B0:TTL0 at the top, which is conventional

def _format_operation_name(op_type: OperationType) -> str:
    """格式化操作类型名称"""
    # Assuming OperationType is an Enum
    return op_type.name

def _generate_text_timeline(physical_lanes: Dict[Board, PhysicalLane], max_width: int) -> str:
    """生成紧凑文本时间轴"""
    lines = []
    all_ops = [op for lane in physical_lanes.values() for op in lane.operations]
    ops_by_channel = _group_by_channel(all_ops)
    
    total_duration = 0
    if all_ops:
        total_duration = max(pop.timestamp_us + cycles_to_us(pop.operation.duration_cycles) for pop in all_ops)
        
    lines.append(f"Timeline View (Total Duration: {total_duration:.1f}μs)")
    lines.append("=" * min(max_width, 80))
    
    sorted_channels = sorted(ops_by_channel.keys(), key=lambda ch: (ch.board.id, ch.channel_type.name, ch.local_id))

    for channel in sorted_channels:
        channel_ops = ops_by_channel[channel]
        patterns = _detect_pulse_patterns(channel_ops)
        op_indices_in_patterns = {idx for p in patterns for idx in p['operation_indices']}
        
        event_strs = []
        # Add patterns first
        for p in patterns:
            p_type = 'TTL' if p['type'] == 'TTL_PULSE' else 'RF'
            icon = '🔲' if p_type == 'TTL' else '📡'
            event_strs.append((p['start_time'], f"{icon} {p_type}[{p['duration']:.1f}μs]"))

        # Add remaining individual ops
        for i, op in enumerate(channel_ops):
            if i not in op_indices_in_patterns:
                op_name = _format_operation_name(op.operation.operation_type)
                event_strs.append((op.timestamp_us, f"⚡ {op_name}"))

        # Sort all events by time and join
        event_strs.sort(key=lambda x: x[0])
        timeline = " → ".join(f"t={t:.1f}:{desc}" for t, desc in event_strs)
        lines.append(f"{channel.global_id:<12} │ {timeline}")
        
    return "\n".join(lines)


