"""
Timeline visualization functions for Morphisms.

This module provides functions to visualize Morphism timelines using both
matplotlib plots and text representations, leveraging compiler components
for precise timing calculations.
"""

from typing import Dict, List, Tuple, Optional, Any
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from ..morphism import Morphism
from ..lanes import merge_board_lanes, PhysicalLane, PhysicalOperation
from ..time_utils import cycles_to_us
from ..types import Board, Channel, OperationType


def visualize_morphism(morphism: Morphism, 
                      mode: str = 'plot', 
                      style: str = 'compact',
                      **kwargs) -> Any:
    """可视化 Morphism 的通用入口函数
    
    Args:
        morphism: 要可视化的 Morphism
        mode: 'plot' (matplotlib) 或 'text' (文本)
        style: 'compact' (紧凑) 或 'proportional' (按比例)
        **kwargs: 传递给具体可视化函数的参数
        
    Returns:
        根据 mode 返回不同类型的结果
    """
    if mode == 'plot':
        return plot_timeline(morphism, style=style, **kwargs)
    elif mode == 'text':
        return text_timeline(morphism, style=style, **kwargs)
    else:
        raise ValueError(f"Unknown visualization mode: {mode}")


def plot_timeline(morphism: Morphism, 
                 style: str = 'compact',
                 figsize: Tuple[int, int] = (12, 6),
                 filename: Optional[str] = None,
                 show_sync: bool = True,
                 **kwargs) -> Tuple[plt.Figure, plt.Axes]:
    """使用 matplotlib 绘制时间轴
    
    Args:
        morphism: 要可视化的 Morphism
        style: 'compact' 或 'proportional'
        figsize: 图片尺寸
        filename: 保存文件名，None 则不保存
        show_sync: 是否显示同步标记
        
    Returns:
        (figure, axes) 元组
    """
    
    # 使用编译器组件计算精确时间线
    physical_lanes = _compute_physical_lanes(morphism)
    
    if not physical_lanes:
        # 处理空 morphism
        fig, ax = plt.subplots(figsize=figsize)
        ax.text(0.5, 0.5, f'Empty Morphism\nDuration: {morphism.total_duration_us:.1f}μs', 
                ha='center', va='center', transform=ax.transAxes)
        return fig, ax
    
    fig, ax = plt.subplots(figsize=figsize)
    
    if style == 'compact':
        _plot_compact_style(ax, physical_lanes, **kwargs)
    else:
        _plot_proportional_style(ax, physical_lanes, **kwargs)
    
    if show_sync:
        sync_points = detect_sync_points(physical_lanes)
        _draw_sync_markers(ax, sync_points)
    
    _setup_plot_aesthetics(ax, morphism.total_duration_us)
    
    if filename:
        fig.savefig(filename, dpi=300, bbox_inches='tight')
        print(f"Timeline plot saved to {filename}")
    
    return fig, ax


def text_timeline(morphism: Morphism, 
                 style: str = 'compact',
                 max_width: int = 100) -> str:
    """生成文本形式的时间轴
    
    Args:
        morphism: 要可视化的 Morphism
        style: 'compact' 或 'proportional' 
        max_width: 最大显示宽度
        
    Returns:
        文本时间轴字符串
    """
    
    if not morphism.lanes:
        return f"Empty Morphism ({morphism.total_duration_us:.1f}μs)"
    
    physical_lanes = _compute_physical_lanes(morphism)
    
    if style == 'compact':
        return _generate_compact_text(physical_lanes, max_width)
    else:
        return _generate_proportional_text(physical_lanes, max_width)


def analyze_morphism_timing(morphism: Morphism) -> Dict[str, Any]:
    """分析 Morphism 的时序特性
    
    Args:
        morphism: 要分析的 Morphism
        
    Returns:
        包含时序分析结果的字典
    """
    physical_lanes = _compute_physical_lanes(morphism)
    sync_points = detect_sync_points(physical_lanes)
    
    return {
        'total_duration_us': morphism.total_duration_us,
        'total_channels': len(morphism.lanes),
        'total_boards': len(physical_lanes),
        'sync_points': len(sync_points),
        'operation_count': sum(len(pl.operations) for pl in physical_lanes.values()),
        'sync_coverage': _calculate_sync_coverage(sync_points, list(morphism.lanes.keys()))
    }


def detect_sync_points(physical_lanes: Dict[Board, PhysicalLane]) -> List[Dict[str, Any]]:
    """检测同步点
    
    Args:
        physical_lanes: 物理Lane字典
        
    Returns:
        同步点列表，每个同步点包含时间和参与的操作
    """
    timestamp_to_ops = {}
    
    for board, physical_lane in physical_lanes.items():
        for pop in physical_lane.operations:
            timestamp = pop.timestamp_cycles
            if timestamp not in timestamp_to_ops:
                timestamp_to_ops[timestamp] = []
            timestamp_to_ops[timestamp].append({
                'board': board,
                'channel': pop.operation.channel,
                'operation': pop.operation
            })
    
    sync_points = []
    for timestamp, ops in timestamp_to_ops.items():
        if len(ops) > 1:  # 多个操作同时发生
            sync_points.append({
                'time_us': cycles_to_us(timestamp),
                'timestamp_cycles': timestamp,
                'operations': ops,
                'channels': [op['channel'] for op in ops]
            })
    
    return sorted(sync_points, key=lambda x: x['timestamp_cycles'])


def detect_pulse_patterns(morphism: Morphism) -> List[Dict[str, Any]]:
    """检测脉冲模式
    
    Args:
        morphism: 要分析的 Morphism
        
    Returns:
        检测到的脉冲模式列表
    """
    physical_lanes = _compute_physical_lanes(morphism)
    patterns = []
    
    for board, physical_lane in physical_lanes.items():
        channel_ops = _group_by_channel(physical_lane.operations)
        for channel, ops in channel_ops.items():
            patterns.extend(_detect_channel_pulses(channel, ops))
    
    return patterns


# ====== 内部实现函数 ======

def _compute_physical_lanes(morphism: Morphism) -> Dict[Board, PhysicalLane]:
    """使用编译器组件计算物理时间线"""
    boards_lanes = morphism.lanes_by_board()
    return {
        board: merge_board_lanes(board, board_lanes)
        for board, board_lanes in boards_lanes.items()
    }


def _group_by_channel(operations: List[PhysicalOperation]) -> Dict[Channel, List[PhysicalOperation]]:
    """按通道分组物理操作"""
    channel_ops = {}
    for pop in operations:
        channel = pop.operation.channel
        if channel not in channel_ops:
            channel_ops[channel] = []
        channel_ops[channel].append(pop)
    
    # 按时间戳排序
    for ops in channel_ops.values():
        ops.sort(key=lambda x: x.timestamp_cycles)
    
    return channel_ops


def _collect_all_sync_points(physical_lanes: Dict[Board, PhysicalLane]) -> List[float]:
    """收集所有关键时间点（同步点和操作边界）"""
    time_points = set([0.0])  # 总是包含起始点
    
    for board, physical_lane in physical_lanes.items():
        for pop in physical_lane.operations:
            # 添加操作开始时间
            time_points.add(pop.timestamp_us)
            # 添加操作结束时间
            end_time = pop.timestamp_us + cycles_to_us(pop.operation.duration_cycles)
            time_points.add(end_time)
    
    # 排序并返回
    return sorted(time_points)


def _create_adaptive_time_mapping(sync_points: List[float]) -> Dict[float, float]:
    """创建自适应时间映射：真实时间 -> 显示位置
    
    策略：
    - 每个同步点之间的间隔至少保证最小可视距离
    - 长时间间隔压缩显示，短时间间隔放大显示
    - 保证同步点在所有通道上垂直对齐
    """
    if len(sync_points) <= 1:
        return {0.0: 0.0}
    
    time_mapping = {}
    current_display_pos = 0.0
    min_segment_width = 1.0  # 最小显示宽度
    max_segment_width = 10.0  # 最大显示宽度
    
    for i, time_point in enumerate(sync_points):
        time_mapping[time_point] = current_display_pos
        
        if i < len(sync_points) - 1:
            # 计算到下一个时间点的间隔
            time_diff = sync_points[i + 1] - time_point
            
            if time_diff == 0:
                # 同时发生的事件，不增加显示位置
                continue
            elif time_diff < 1.0:  # 小于 1μs，放大显示
                display_width = max(min_segment_width, time_diff * 2)
            elif time_diff > 100.0:  # 大于 100μs，压缩显示
                display_width = min(max_segment_width, 2 + time_diff / 50)
            else:  # 1-100μs，线性映射
                display_width = min_segment_width + (time_diff / 100.0) * (max_segment_width - min_segment_width)
            
            current_display_pos += display_width
    
    return time_mapping


def _draw_adaptive_channel_operations(ax: plt.Axes, channel: Channel, 
                                    ops: List[PhysicalOperation], 
                                    y_pos: int, time_mapping: Dict[float, float]):
    """使用自适应时间映射绘制通道操作"""
    
    def map_time_to_display(time_us: float) -> float:
        """将真实时间映射到显示位置"""
        # 找到最接近的映射点进行插值
        sorted_times = sorted(time_mapping.keys())
        
        if time_us <= sorted_times[0]:
            return time_mapping[sorted_times[0]]
        if time_us >= sorted_times[-1]:
            return time_mapping[sorted_times[-1]]
        
        # 线性插值
        for i in range(len(sorted_times) - 1):
            t1, t2 = sorted_times[i], sorted_times[i + 1]
            if t1 <= time_us <= t2:
                ratio = (time_us - t1) / (t2 - t1) if t2 > t1 else 0
                return time_mapping[t1] + ratio * (time_mapping[t2] - time_mapping[t1])
        
        return time_mapping[sorted_times[-1]]
    
    # 检测脉冲模式并绘制
    pulse_patterns = _detect_channel_pulses(channel, ops)
    drawn_ops = set()
    
    # 绘制脉冲模式
    for pattern in pulse_patterns:
        start_display = map_time_to_display(pattern['start_time'])
        end_display = map_time_to_display(pattern['start_time'] + pattern['duration'])
        width = max(0.5, end_display - start_display)  # 确保最小宽度
        
        if pattern['type'] == 'TTL_PULSE':
            color = 'lightgreen'
            label = f"TTL({pattern['duration']:.1f}μs)"
        elif pattern['type'] == 'RF_PULSE':
            color = 'orange'
            label = f"RF({pattern['duration']:.1f}μs)"
        else:
            color = 'lightgray'
            label = f"{pattern['duration']:.1f}μs"
        
        # 绘制脉冲矩形
        rect = plt.Rectangle(
            (start_display, y_pos - 0.4),
            width, 0.8,
            facecolor=color, alpha=0.7,
            edgecolor='black', linewidth=1
        )
        ax.add_patch(rect)
        
        # 添加标签
        ax.text(start_display + width/2, y_pos, label,
               ha='center', va='center', fontsize=8, fontweight='bold')
        
        # 标记已绘制的操作
        for op_idx in pattern.get('operation_indices', []):
            drawn_ops.add(op_idx)
    
    # 绘制其他单独操作
    for i, pop in enumerate(ops):
        if i in drawn_ops:
            continue
        
        display_pos = map_time_to_display(pop.timestamp_us)
        op_type = pop.operation.operation_type
        color = _get_operation_color(op_type)
        symbol = _get_operation_symbol_text(op_type)
        
        # 绘制为垂直标记线 (使用相对位置)
        ax.plot([display_pos, display_pos], [y_pos-0.4, y_pos+0.4], 
               color=color, linewidth=2)
        
        # 添加操作标签
        ax.text(display_pos, y_pos + 0.2, symbol, ha='center', va='bottom', 
               fontsize=6, rotation=90)


def _setup_adaptive_time_ticks(ax: plt.Axes, sync_points: List[float], 
                              time_mapping: Dict[float, float]):
    """设置自适应时间轴刻度"""
    # 选择重要的时间点作为刻度
    important_times = []
    display_positions = []
    
    # 总是包含起始点
    if sync_points:
        important_times.append(sync_points[0])
        display_positions.append(time_mapping[sync_points[0]])
    
    # 添加其他重要时间点（避免过于密集）
    last_display_pos = time_mapping.get(sync_points[0], 0) if sync_points else 0
    min_tick_spacing = 2.0  # 最小刻度间距
    
    for time_point in sync_points[1:]:
        display_pos = time_mapping[time_point]
        if display_pos - last_display_pos >= min_tick_spacing:
            important_times.append(time_point)
            display_positions.append(display_pos)
            last_display_pos = display_pos
    
    # 设置x轴刻度
    ax.set_xticks(display_positions)
    ax.set_xticklabels([f"{t:.1f}μs" for t in important_times], rotation=45)
    ax.set_xlabel("时间 (自适应尺度)")


def _get_operation_symbol_text(op_type: OperationType) -> str:
    """获取操作的文本符号"""
    symbol_map = {
        OperationType.TTL_ON: "ON",
        OperationType.TTL_OFF: "OFF",
        OperationType.TTL_INIT: "INIT",
        OperationType.RWG_INIT: "INIT", 
        OperationType.RWG_SET_CARRIER: "CARR",
        OperationType.RWG_LOAD_COEFFS: "LOAD",
        OperationType.RWG_UPDATE_PARAMS: "PLAY",
        OperationType.RWG_RF_SWITCH: "RF",
        OperationType.SYNC_MASTER: "SYNC",
        OperationType.SYNC_SLAVE: "SYNC",
    }
    return symbol_map.get(op_type, "OP")


def _plot_compact_style(ax: plt.Axes, physical_lanes: Dict[Board, PhysicalLane], **kwargs):
    """绘制紧凑风格的时间轴 - 自适应时间尺度，保证操作可见性和同步对齐"""
    
    # 1. 收集所有关键时间点（同步点）
    sync_points = _collect_all_sync_points(physical_lanes)
    
    # 2. 创建自适应时间映射
    time_mapping = _create_adaptive_time_mapping(sync_points)
    
    # 3. 绘制通道操作
    y_position = 0
    channel_labels = []
    
    for board, physical_lane in physical_lanes.items():
        channel_ops = _group_by_channel(physical_lane.operations)
        
        for channel, ops in channel_ops.items():
            _draw_adaptive_channel_operations(ax, channel, ops, y_position, time_mapping)
            channel_labels.append(channel.global_id)
            y_position += 1
    
    ax.set_yticks(range(y_position))
    ax.set_yticklabels(channel_labels)
    
    # 4. 设置自适应时间轴标记
    _setup_adaptive_time_ticks(ax, sync_points, time_mapping)


def _plot_proportional_style(ax: plt.Axes, physical_lanes: Dict[Board, PhysicalLane], **kwargs):
    """绘制按比例风格的时间轴"""
    # 目前与 compact 相同，未来可以扩展
    _plot_compact_style(ax, physical_lanes, **kwargs)


def _draw_channel_operations(ax: plt.Axes, channel: Channel, ops: List[PhysicalOperation], 
                           y_pos: int, style: str):
    """绘制单个通道的操作"""
    
    # 检测脉冲模式
    pulse_patterns = _detect_channel_pulses(channel, ops)
    drawn_ops = set()  # 跟踪已绘制的操作
    
    # 首先绘制脉冲
    for pattern in pulse_patterns:
        if pattern['type'] == 'TTL_PULSE':
            color = 'green'
            alpha = 0.8
        elif pattern['type'] == 'RF_PULSE':
            color = 'orange' 
            alpha = 0.8
        else:
            color = 'gray'
            alpha = 0.6
        
        # 绘制脉冲矩形
        rect = plt.Rectangle(
            (pattern['start_time'], y_pos - 0.3),
            pattern['duration'],
            0.6,
            facecolor=color,
            alpha=alpha,
            edgecolor='black',
            linewidth=0.5
        )
        ax.add_patch(rect)
        
        # 添加脉冲标签
        ax.text(
            pattern['start_time'] + pattern['duration'] / 2,
            y_pos,
            f"{pattern['duration']:.1f}μs",
            ha='center', va='center',
            fontsize=8, fontweight='bold'
        )
        
        # 标记这些操作为已绘制
        for op_idx in pattern.get('operation_indices', []):
            drawn_ops.add(op_idx)
    
    # 绘制其他非脉冲操作
    for i, pop in enumerate(ops):
        if i in drawn_ops:
            continue
            
        time_us = pop.timestamp_us
        op_type = pop.operation.operation_type
        
        # 选择颜色和符号
        color = _get_operation_color(op_type)
        
        # 绘制为垂直线
        ax.axvline(x=time_us, ymin=(y_pos-0.4)/10, ymax=(y_pos+0.4)/10, 
                  color=color, linewidth=3, alpha=0.8)


def _detect_channel_pulses(channel: Channel, ops: List[PhysicalOperation]) -> List[Dict[str, Any]]:
    """检测单个通道的脉冲模式"""
    patterns = []
    i = 0
    
    while i < len(ops) - 1:
        current_op = ops[i]
        next_op = ops[i + 1]
        
        # TTL 脉冲检测：ON 后面跟 OFF
        if (current_op.operation.operation_type == OperationType.TTL_ON and
            next_op.operation.operation_type == OperationType.TTL_OFF):
            
            pulse_start = current_op.timestamp_us
            pulse_end = next_op.timestamp_us
            duration = pulse_end - pulse_start
            
            patterns.append({
                'type': 'TTL_PULSE',
                'start_time': pulse_start,
                'duration': duration,
                'channel': channel,
                'operation_indices': [i, i + 1]
            })
            i += 2  # 跳过这两个操作
            
        # RF 脉冲检测：RF_SWITCH(ON) 后面跟 RF_SWITCH(OFF)
        elif (current_op.operation.operation_type == OperationType.RWG_RF_SWITCH and
              next_op.operation.operation_type == OperationType.RWG_RF_SWITCH):
            
            # 检查是否是 RF ON → RF OFF 的转换
            if (hasattr(current_op.operation.end_state, 'rf_on') and
                hasattr(next_op.operation.end_state, 'rf_on') and
                current_op.operation.end_state.rf_on and
                not next_op.operation.end_state.rf_on):
                
                pulse_start = current_op.timestamp_us
                pulse_end = next_op.timestamp_us
                duration = pulse_end - pulse_start
                
                patterns.append({
                    'type': 'RF_PULSE',
                    'start_time': pulse_start,
                    'duration': duration,
                    'channel': channel,
                    'operation_indices': [i, i + 1]
                })
                i += 2
            else:
                i += 1
        else:
            i += 1
    
    return patterns


def _get_operation_color(op_type: OperationType) -> str:
    """获取操作类型对应的颜色"""
    color_map = {
        OperationType.TTL_ON: 'green',
        OperationType.TTL_OFF: 'red',
        OperationType.TTL_INIT: 'blue',
        OperationType.RWG_RF_SWITCH: 'orange',
        OperationType.RWG_INIT: 'purple',
        OperationType.RWG_SET_CARRIER: 'brown',
        OperationType.RWG_LOAD_COEFFS: 'pink',
        OperationType.RWG_UPDATE_PARAMS: 'olive',
        OperationType.IDENTITY: 'lightgray',
        OperationType.SYNC_MASTER: 'darkblue',
        OperationType.SYNC_SLAVE: 'darkgreen',
    }
    return color_map.get(op_type, 'gray')


def _draw_sync_markers(ax: plt.Axes, sync_points: List[Dict[str, Any]]):
    """绘制同步标记"""
    for i, sync_point in enumerate(sync_points):
        time_us = sync_point['time_us']
        
        # 绘制垂直同步线
        ax.axvline(x=time_us, color='red', linestyle='--', alpha=0.7, linewidth=2)
        
        # 添加同步点标签
        ax.text(time_us, ax.get_ylim()[1] * 1.02, f"S{i+1}", 
               ha='center', va='bottom', color='red', fontweight='bold')


def _setup_plot_aesthetics(ax: plt.Axes, total_duration_us: float):
    """设置图表美学属性"""
    ax.set_xlabel('Time (μs)')
    ax.set_title(f'Morphism Timeline ({total_duration_us:.1f}μs)')
    ax.grid(True, alpha=0.3)
    ax.set_xlim(0, total_duration_us * 1.05)
    
    # 设置合适的Y轴范围
    ylim = ax.get_ylim()
    ax.set_ylim(ylim[0] - 0.5, ylim[1] + 0.5)


def _generate_compact_text(physical_lanes: Dict[Board, PhysicalLane], max_width: int) -> str:
    """生成紧凑文本时间轴 - 显示自适应时间信息"""
    lines = []
    
    # 计算自适应时间映射
    sync_points = _collect_all_sync_points(physical_lanes)
    time_mapping = _create_adaptive_time_mapping(sync_points)
    
    lines.append(f"Timeline View (Adaptive Scale):")
    lines.append("=" * min(max_width, 80))
    
    # 显示时间轴信息
    if len(sync_points) > 1:
        time_info = f"Time points: {sync_points[0]:.1f}μs"
        if len(sync_points) > 2:
            time_info += f" → ... → {sync_points[-1]:.1f}μs"
        elif len(sync_points) == 2:
            time_info += f" → {sync_points[-1]:.1f}μs"
        lines.append(time_info)
        lines.append("")
    
    for board, physical_lane in physical_lanes.items():
        channel_ops = _group_by_channel(physical_lane.operations)
        
        for channel, ops in channel_ops.items():
            # 检测脉冲模式
            patterns = _detect_channel_pulses(channel, ops)
            
            if patterns:
                # 显示脉冲模式与时间信息
                pattern_strs = []
                for pattern in patterns:
                    start_t = pattern['start_time']
                    duration = pattern['duration']
                    
                    if pattern['type'] == 'TTL_PULSE':
                        pattern_strs.append(f"🔲 TTL[t={start_t:.1f}μs]({duration:.1f}μs)")
                    elif pattern['type'] == 'RF_PULSE':
                        pattern_strs.append(f"📡 RF[t={start_t:.1f}μs]({duration:.1f}μs)")
                
                timeline = " → ".join(pattern_strs)
            else:
                # 显示详细操作与时间戳
                op_strs = []
                for pop in ops:
                    op_name = _format_operation_name(pop.operation.operation_type)
                    op_strs.append(f"t={pop.timestamp_us:.1f}:{op_name}")
                timeline = " → ".join(op_strs)
            
            lines.append(f"{channel.global_id:<12} │ {timeline}")
    
    # 显示时间尺度压缩信息
    if len(sync_points) > 2:
        lines.append("")
        lines.append("📏 Time scale: adaptive (short intervals expanded, long intervals compressed)")
    
    return "\n".join(lines)


def _generate_proportional_text(physical_lanes: Dict[Board, PhysicalLane], max_width: int) -> str:
    """生成按比例文本时间轴"""
    # 目前与 compact 相同，未来可以扩展
    return _generate_compact_text(physical_lanes, max_width)


def _format_operation_name(op_type: OperationType) -> str:
    """格式化操作类型名称"""
    name_map = {
        OperationType.TTL_INIT: "INIT",
        OperationType.TTL_ON: "ON",
        OperationType.TTL_OFF: "OFF", 
        OperationType.RWG_INIT: "RWG_INIT",
        OperationType.RWG_SET_CARRIER: "SET_CARRIER",
        OperationType.RWG_LOAD_COEFFS: "LOAD",
        OperationType.RWG_UPDATE_PARAMS: "PLAY",
        OperationType.RWG_RF_SWITCH: "RF_SW",
        OperationType.IDENTITY: "WAIT",
        OperationType.SYNC_MASTER: "SYNC_M",
        OperationType.SYNC_SLAVE: "SYNC_S",
    }
    return name_map.get(op_type, str(op_type))


def _calculate_sync_coverage(sync_points: List[Dict[str, Any]], all_channels: List[Channel]) -> float:
    """计算同步覆盖率"""
    if not sync_points or not all_channels:
        return 0.0
    
    sync_channels = set()
    for sp in sync_points:
        sync_channels.update(sp['channels'])
    
    return len(sync_channels) / len(all_channels)