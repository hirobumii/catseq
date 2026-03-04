"""
Standalone and testable script for Morphism timeline visualization.

This file contains all necessary mock objects and the core visualization logic
to produce a timeline plot from a Morphism object. It is designed to be
run directly for testing and validation.
"""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict

# Assume these are correctly imported from your project structure
from ..morphism import Morphism
from ..lanes import merge_board_lanes, PhysicalLane, PhysicalOperation
from ..time_utils import cycles_to_us
from ..types import Board, Channel, OperationType
from ..types.common import BlackBoxAtomicMorphism
from .rwg_analyzer import analyze_rwg_timeline, _evaluate_taylor_series


# ==============================================================================
# CORE VISUALIZATION LOGIC (Refactored and Cleaned)
# ==============================================================================

def plot_timeline(morphism: Morphism,
                  figsize: Tuple[int, int] = (15, 8),
                  filename: Optional[str] = None,
                  show_sync: bool = True,
                  channel_styles: Optional[Dict[Any, Dict[str, str]]] = None,
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

    _plot_adaptive_timeline(ax, physical_lanes, channel_styles=channel_styles, **kwargs)

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

def _detect_loop_blackbox(ops: List[PhysicalOperation]) -> Dict[str, Any] | None:
    """检测循环黑盒模式"""
    # 检查是否只有一个操作且是黑盒操作
    if len(ops) == 1:
        op = ops[0].operation
        if (isinstance(op, BlackBoxAtomicMorphism) and
            op.operation_type == OperationType.OPAQUE_OASM_FUNC and
            op.metadata.get('loop_type') == 'repeat'):

            loop_count = op.metadata.get('loop_count', '?')
            unit_duration = op.metadata.get('unit_duration', 0)
            unit_duration_us = cycles_to_us(unit_duration)

            return {
                'type': 'LOOP_BLACKBOX',
                'loop_count': loop_count,
                'unit_duration_us': unit_duration_us,
                'total_duration_us': cycles_to_us(op.duration_cycles),
                'start_time': ops[0].timestamp_us,
                'operation_index': 0
            }

    return None

def _draw_loop_blackbox(ax: plt.Axes, loop_info: Dict[str, Any], y_pos: int, time_mapping: Dict[float, float]):
    """绘制循环黑盒：用框框出来，右上角标上乘号和次数"""
    start_display = _map_time_to_display(loop_info['start_time'], time_mapping)
    end_display = _map_time_to_display(loop_info['start_time'] + loop_info['total_duration_us'], time_mapping)
    width = max(1.0, end_display - start_display)

    # 绘制带圆角的边框
    bbox = FancyBboxPatch(
        (start_display, y_pos - 0.45), width, 0.9,
        boxstyle="round,pad=0.02",
        facecolor='lightblue',
        edgecolor='darkblue',
        linewidth=2,
        alpha=0.7
    )
    ax.add_patch(bbox)

    # 添加循环标记 - 右上角的乘号和次数
    loop_count = loop_info['loop_count']
    unit_duration = loop_info['unit_duration_us']

    # 循环次数标记 - 放在框的右上角
    ax.text(end_display - width * 0.05, y_pos + 0.35,
           f"×{loop_count}",
           ha='right', va='bottom',
           fontsize=10, fontweight='bold',
           color='darkred',
           bbox=dict(boxstyle="round,pad=0.1", facecolor='white', edgecolor='darkred', alpha=0.9))

    # 主标签 - 在框的中央
    main_label = f"Loop({unit_duration:.1f}μs)"
    ax.text(start_display + width/2, y_pos,
           main_label,
           ha='center', va='center',
           fontsize=9, fontweight='bold',
           color='darkblue')

    # 总时长标签 - 在框的下方
    total_label = f"Total: {loop_info['total_duration_us']:.1f}μs"
    ax.text(start_display + width/2, y_pos - 0.3,
           total_label,
           ha='center', va='center',
           fontsize=7, style='italic',
           color='gray')

def _detect_pulse_patterns(ops: List[PhysicalOperation]) -> List[Dict[str, Any]]:
    """检测单个通道的脉冲模式"""
    patterns = []
    used_indices = set()
    i = 0
    
    while i < len(ops):
        if i in used_indices:
            i += 1
            continue
            
        current_op = ops[i]
        
        # TTL Pulse: 检测 TTL_ON 然后向前找最近的 TTL_OFF
        if current_op.operation.operation_type == OperationType.TTL_ON:
            for j in range(i + 1, len(ops)):
                if j in used_indices:
                    continue
                next_op = ops[j]
                if next_op.operation.operation_type == OperationType.TTL_OFF:
                    patterns.append({
                        'type': 'TTL_PULSE', 'start_time': current_op.timestamp_us,
                        'duration': next_op.timestamp_us - current_op.timestamp_us,
                        'operation_indices': {i, j}
                    })
                    used_indices.add(i)
                    used_indices.add(j)
                    break

        # RF Pulse: 检测 RF ON 然后向前找最近的 RF OFF
        elif (current_op.operation.operation_type == OperationType.RWG_RF_SWITCH and
              hasattr(current_op.operation, 'end_state') and
              current_op.operation.end_state.rf_on):
            for j in range(i + 1, len(ops)):
                if j in used_indices:
                    continue
                next_op = ops[j]
                if (next_op.operation.operation_type == OperationType.RWG_RF_SWITCH and
                    hasattr(next_op.operation, 'end_state') and
                    not next_op.operation.end_state.rf_on):
                    patterns.append({
                        'type': 'RF_PULSE', 'start_time': current_op.timestamp_us,
                        'duration': next_op.timestamp_us - current_op.timestamp_us,
                        'operation_indices': {i, j}
                    })
                    used_indices.add(i)
                    used_indices.add(j)
                    break
        
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
                                      y_pos: int, time_mapping: Dict[float, float], 
                                      channel=None, channel_styles=None):
    """使用自适应时间映射绘制通道操作"""
    # 检查是否需要使用特殊样式
    style_config = None
    if channel_styles and channel and channel in channel_styles:
        style_config = channel_styles[channel]
    
    # 如果配置了特殊样式（freq 或 amp），使用连续曲线渲染
    if style_config and style_config.get("style") in ["freq", "amp"]:
        _draw_taylor_curve(ax, ops, y_pos, time_mapping, style_config["style"])
        return
    
    # 检测循环黑盒模式
    loop_blackbox = _detect_loop_blackbox(ops)
    if loop_blackbox:
        _draw_loop_blackbox(ax, loop_blackbox, y_pos, time_mapping)
        return

    # 原有的离散操作点逻辑
    pulse_patterns = _detect_pulse_patterns(ops)
    pulse_op_indices = set()
    for p in pulse_patterns:
        pulse_op_indices.update(p['operation_indices'])

    # 绘制脉冲背景色块（只覆盖配对的on/off操作，不影响中间操作的显示）
    for pattern in pulse_patterns:
        start_display = _map_time_to_display(pattern['start_time'], time_mapping)
        end_display = _map_time_to_display(pattern['start_time'] + pattern['duration'], time_mapping)
        width = max(0.5, end_display - start_display)
        
        color, label_prefix = ('lightgreen', 'TTL') if pattern['type'] == 'TTL_PULSE' else ('orange', 'RF')
        label = f"{label_prefix}({pattern['duration']:.1f}μs)"
        
        # 绘制背景色块
        rect = plt.Rectangle((start_display, y_pos - 0.4), width, 0.8,
                             facecolor=color, alpha=0.3, edgecolor='black', linewidth=1)
        ax.add_patch(rect)
        ax.text(start_display + width/2, y_pos - 0.3, label, ha='center', va='center', 
                fontsize=8, fontweight='bold', color='black')

    # 绘制所有操作（除了在脉冲模式中已配对的on/off操作）
    for i, pop in enumerate(ops):
        display_pos = _map_time_to_display(pop.timestamp_us, time_mapping)
        op_type = pop.operation.operation_type
        color = _get_operation_color(op_type)
        symbol = _get_operation_symbol_text(op_type)
        
        # 对于脉冲模式中的配对操作，只画简化标记
        if i in pulse_op_indices:
            # 配对的on/off操作画小圆点
            ax.plot(display_pos, y_pos, 'o', color=color, markersize=4)
            ax.text(display_pos, y_pos + 0.15, symbol, ha='center', va='bottom', 
                   fontsize=6, rotation=0, color=color, fontweight='bold')
        else:
            # 改进单线操作的可视化
            _draw_enhanced_operation(ax, pop, display_pos, y_pos, color, symbol)

def _draw_enhanced_operation(ax: plt.Axes, pop: PhysicalOperation, display_pos: float, 
                           y_pos: int, color: str, symbol: str):
    """增强的单个操作绘制，提高可读性"""
    op_type = pop.operation.operation_type
    
    # 根据操作类型选择不同的可视化风格
    if op_type in [OperationType.RWG_INIT, OperationType.TTL_INIT]:
        # INIT 操作：画粗实线 + 背景框
        ax.plot([display_pos, display_pos], [y_pos-0.35, y_pos+0.35], 
               color=color, linewidth=4, solid_capstyle='round')
        # 添加浅色背景框
        rect = plt.Rectangle((display_pos-0.15, y_pos-0.35), 0.3, 0.7,
                            facecolor=color, alpha=0.2, edgecolor='none')
        ax.add_patch(rect)
        # 标签放在右侧，避免重叠
        ax.text(display_pos + 0.2, y_pos, symbol, ha='left', va='center', 
               fontsize=8, fontweight='bold', color=color)
                
    elif op_type in [OperationType.RWG_LOAD_COEFFS, OperationType.RWG_UPDATE_PARAMS]:
        # LOAD/PLAY 操作：画钻石形状
        diamond_size = 0.15
        diamond_x = [display_pos-diamond_size, display_pos, display_pos+diamond_size, display_pos]
        diamond_y = [y_pos, y_pos+diamond_size, y_pos, y_pos-diamond_size]
        ax.plot(diamond_x + [diamond_x[0]], diamond_y + [diamond_y[0]], 
               color=color, linewidth=2, marker='o', markersize=3, markerfacecolor=color)
        ax.fill(diamond_x, diamond_y, color=color, alpha=0.3)
        # 标签放在上方
        ax.text(display_pos, y_pos + 0.25, symbol, ha='center', va='bottom', 
               fontsize=7, fontweight='bold', color='black')
    
    elif op_type in [OperationType.SYNC_MASTER, OperationType.SYNC_SLAVE]:
        # SYNC 操作：画双线 + 强调标记
        ax.plot([display_pos-0.05, display_pos-0.05], [y_pos-0.3, y_pos+0.3], 
               color=color, linewidth=3, solid_capstyle='round')
        ax.plot([display_pos+0.05, display_pos+0.05], [y_pos-0.3, y_pos+0.3], 
               color=color, linewidth=3, solid_capstyle='round')
        # 添加星形标记
        ax.plot(display_pos, y_pos, '*', color=color, markersize=8, markeredgecolor='black')
        # 标签放在左侧
        ax.text(display_pos - 0.2, y_pos, symbol, ha='right', va='center', 
               fontsize=8, fontweight='bold', color=color)
    
    elif op_type == OperationType.RWG_SET_CARRIER:
        # CARRIER 操作：画波浪线形状
        import numpy as np
        wave_x = np.linspace(display_pos-0.1, display_pos+0.1, 20)
        wave_y = y_pos + 0.1 * np.sin(15 * (wave_x - display_pos))
        ax.plot(wave_x, wave_y, color=color, linewidth=2)
        # 垂直指示线
        ax.plot([display_pos, display_pos], [y_pos-0.2, y_pos+0.2], 
               color=color, linewidth=1, linestyle='--', alpha=0.7)
        # 标签放在下方
        ax.text(display_pos, y_pos - 0.3, symbol, ha='center', va='top', 
               fontsize=7, fontweight='bold', color=color)
    
    else:
        # 其他操作：传统垂直线但改进样式
        ax.plot([display_pos, display_pos], [y_pos-0.3, y_pos+0.3], 
               color=color, linewidth=2.5, solid_capstyle='round')
        # 添加圆形端点
        ax.plot(display_pos, y_pos+0.3, 'o', color=color, markersize=3)
        ax.plot(display_pos, y_pos-0.3, 'o', color=color, markersize=3)
        # 标签放在右侧，水平显示
        ax.text(display_pos + 0.1, y_pos, symbol, ha='left', va='center', 
               fontsize=7, fontweight='bold', color=color, rotation=0)

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
    ax.set_xticklabels([f"{t:.3f}" for t in important_times], rotation=45, ha="right")
    ax.set_xlabel("Time (μs) - Adaptive Scale")

def _plot_adaptive_timeline(ax: plt.Axes, physical_lanes: Dict[Board, PhysicalLane], channel_styles=None, **kwargs):
    """绘制自适应时间尺度的图表"""
    event_times = _collect_all_event_times(physical_lanes)
    time_mapping = _create_adaptive_time_mapping(event_times)

    all_ops = [op for lane in physical_lanes.values() for op in lane.operations]
    ops_by_channel = _group_by_channel(all_ops)
    sorted_channels = sorted(ops_by_channel.keys(), key=lambda ch: (ch.board.id, ch.channel_type.name, ch.local_id))

    # 构建显示通道列表：对于有 freq/amp style 的通道，创建两行
    display_channels = []
    labels = []

    for channel in sorted_channels:
        style_config = None
        if channel_styles and channel in channel_styles:
            style_config = channel_styles[channel]

        if style_config and style_config.get("style") in ["freq", "amp"]:
            # 为 freq/amp 通道创建两行
            # 上行：默认操作显示
            display_channels.append((channel, "default"))
            base_name = style_config.get('name', channel.global_id)
            labels.append(f"{base_name} (ops)")

            # 下行：曲线显示
            display_channels.append((channel, style_config["style"]))
            labels.append(f"{base_name} ({style_config['style']})")
        else:
            # 普通通道：单行显示
            display_channels.append((channel, "default"))
            if style_config and 'name' in style_config:
                labels.append(style_config['name'])
            else:
                labels.append(channel.global_id)

    # 绘制所有显示通道
    for y_pos, (channel, display_mode) in enumerate(display_channels):
        ops = ops_by_channel[channel]

        if display_mode == "default":
            # 默认显示：不使用曲线样式
            _draw_adaptive_channel_operations(ax, ops, y_pos, time_mapping, channel=channel, channel_styles=None)
        else:
            # 曲线显示：使用指定的样式
            _draw_taylor_curve(ax, ops, y_pos, time_mapping, display_mode)

    ax.set_yticks(range(len(display_channels)))
    ax.set_yticklabels(labels)
    ax.set_ylim(-0.5, len(display_channels) - 0.5)
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

        # 检测循环黑盒
        loop_blackbox = _detect_loop_blackbox(channel_ops)
        if loop_blackbox:
            loop_count = loop_blackbox['loop_count']
            unit_duration = loop_blackbox['unit_duration_us']
            total_duration = loop_blackbox['total_duration_us']
            timeline = f"🔁 Loop×{loop_count}({unit_duration:.1f}μs) → Total: {total_duration:.1f}μs"
            lines.append(f"{channel.global_id:<12} │ {timeline}")
            continue

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


# ==============================================================================
# TAYLOR CURVE VISUALIZATION FUNCTIONS
# ==============================================================================

def _find_previous_load(ops: List[PhysicalOperation]) -> Optional[PhysicalOperation]:
    """从操作列表中找到最近的 LOAD 操作"""
    from ..types.common import OperationType
    for op in reversed(ops):
        if op.operation.operation_type == OperationType.RWG_LOAD_COEFFS:
            return op
    return None

def _extract_taylor_coeffs_from_ops(ops: List[PhysicalOperation], curve_type: str) -> Optional[Tuple]:
    """从操作序列提取 Taylor 系数"""
    from ..types.common import OperationType
    
    for i, op in enumerate(ops):
        if (op.operation.operation_type == OperationType.RWG_UPDATE_PARAMS and 
            op.operation.duration_cycles > 0):
            # 这是一个有持续时间的 PLAY 操作，找配对的 LOAD
            paired_load = _find_previous_load(ops[:i])
            if paired_load and hasattr(paired_load.operation.end_state, 'pending_waveforms'):
                waveforms = paired_load.operation.end_state.pending_waveforms
                if waveforms:
                    if curve_type == "freq":
                        return waveforms[0].freq_coeffs
                    elif curve_type == "amp":
                        return waveforms[0].amp_coeffs
    return None

def _evaluate_taylor_series(coeffs: Tuple, t: float) -> float:
    """计算 Taylor 级数在时间 t 的值"""
    if not coeffs:
        return 0.0
    
    result = coeffs[0] if coeffs[0] is not None else 0.0
    for i, coeff in enumerate(coeffs[1:], 1):
        if coeff is not None:
            result += coeff * (t ** i)
    return result

def _analyze_rwg_timeline(ops: List[PhysicalOperation], curve_type: str) -> List[Dict]:
    """分析 RWG 操作序列，构建完整的频率/振幅时间轴"""
    from ..types.common import OperationType
    from ..time_utils import cycles_to_us
    
    segments = []
    current_rf_state = False
    current_static_value = 0.0
    last_timestamp = 0.0
    
    # 状态追踪变量
    events = []  # 收集所有状态变化事件
    
    for i, op in enumerate(ops):
        op_start_time = op.timestamp_us
        
        # 在处理当前操作前，先添加之前状态的延续段（如果有间隙）
        if segments and op_start_time > last_timestamp:
            # 延续之前的状态
            prev_segment = segments[-1]
            if prev_segment['type'] == 'static':
                segments.append({
                    'type': 'static',
                    'start_time': last_timestamp,
                    'end_time': op_start_time,
                    'value': prev_segment['value'],
                    'rf_on': prev_segment['rf_on']
                })
        
        # 首先更新当前静态值（从任何 RWGActive 状态的 snapshot 中）
        if hasattr(op.operation, 'end_state') and hasattr(op.operation.end_state, 'snapshot'):
            snapshot = op.operation.end_state.snapshot
            if snapshot:
                if curve_type == "freq":
                    current_static_value = snapshot[0].freq
                elif curve_type == "amp":
                    current_static_value = snapshot[0].amp
                print(f"  更新静态值: {curve_type}={current_static_value}")
        
        if op.operation.operation_type == OperationType.RWG_RF_SWITCH:
            # RF 状态变化
            if hasattr(op.operation, 'end_state'):
                new_rf_state = op.operation.end_state.rf_on
                print(f"  RF 切换: {current_rf_state} -> {new_rf_state}")
                if new_rf_state != current_rf_state:
                    current_rf_state = new_rf_state
                    # RF 状态变化影响显示值
                    display_value = 0.0 if not current_rf_state else current_static_value
                    print(f"  显示值: {display_value}")
                    
                    segments.append({
                        'type': 'rf_switch',
                        'start_time': op_start_time,
                        'end_time': op_start_time,  # 瞬时操作
                        'rf_on': current_rf_state,
                        'value': display_value
                    })
        
        elif op.operation.operation_type == OperationType.RWG_UPDATE_PARAMS:
            if op.operation.duration_cycles > 0:
                # Ramp 段：使用 Taylor 系数
                duration_us = cycles_to_us(op.operation.duration_cycles)
                
                # 找配对的 LOAD 操作获取系数
                paired_load = _find_previous_load(ops[:i])
                ramp_coeffs = None
                if paired_load and hasattr(paired_load.operation.end_state, 'pending_waveforms'):
                    waveforms = paired_load.operation.end_state.pending_waveforms
                    if waveforms:
                        if curve_type == "freq":
                            ramp_coeffs = waveforms[0].freq_coeffs
                        elif curve_type == "amp":
                            ramp_coeffs = waveforms[0].amp_coeffs
                
                segments.append({
                    'type': 'ramp',
                    'start_time': op_start_time,
                    'end_time': op_start_time + duration_us,
                    'coeffs': ramp_coeffs,
                    'rf_on': current_rf_state
                })
                
                # 更新 ramp 结束后的静态值
                if ramp_coeffs and ramp_coeffs[0] is not None:
                    # 计算 ramp 结束时的值
                    end_value = _evaluate_taylor_series(ramp_coeffs, duration_us)
                    current_static_value = end_value
                
                last_timestamp = op_start_time + duration_us
            else:
                # 瞬时 PLAY 操作 - 可能改变静态值
                if hasattr(op.operation, 'end_state') and hasattr(op.operation.end_state, 'snapshot'):
                    snapshot = op.operation.end_state.snapshot
                    if snapshot:
                        if curve_type == "freq":
                            current_static_value = snapshot[0].freq
                        elif curve_type == "amp":
                            current_static_value = snapshot[0].amp
                
                # 添加新的静态段
                display_value = 0.0 if not current_rf_state else current_static_value
                segments.append({
                    'type': 'static',
                    'start_time': op_start_time,
                    'end_time': op_start_time,  # 瞬时，会在下次状态变化时结束
                    'value': display_value,
                    'rf_on': current_rf_state
                })
                
                last_timestamp = op_start_time
        
        elif op.operation.operation_type == OperationType.RWG_LOAD_COEFFS:
            # LOAD 操作可能包含新的静态值信息
            if (hasattr(op.operation, 'end_state') and 
                hasattr(op.operation.end_state, 'pending_waveforms') and
                op.operation.end_state.pending_waveforms):
                
                waveform = op.operation.end_state.pending_waveforms[0]
                target_coeffs = waveform.freq_coeffs if curve_type == "freq" else waveform.amp_coeffs
                
                # 检查是否为静态值（只有常数项，其他为0或None）
                if target_coeffs and target_coeffs[0] is not None:
                    is_static = all(coeff is None or coeff == 0 for coeff in target_coeffs[1:])
                    if is_static:
                        current_static_value = target_coeffs[0]
            
            last_timestamp = op_start_time
        
        else:
            last_timestamp = op_start_time
    
    # 修正所有未结束的段，延续到时间轴末尾
    if segments:
        timeline_end = max(op.timestamp_us for op in ops) if ops else 0.0
        for segment in segments:
            if segment['end_time'] == segment['start_time']:  # 瞬时操作
                # 找到下一个状态变化点
                next_change = timeline_end
                for other_seg in segments:
                    if other_seg['start_time'] > segment['start_time']:
                        next_change = min(next_change, other_seg['start_time'])
                segment['end_time'] = next_change
    
    return segments

def _draw_taylor_curve(ax: plt.Axes, ops: List[PhysicalOperation], y_pos: int,
                      time_mapping: Dict[float, float], curve_type: str):
    """绘制基于 Taylor 系数的连续曲线"""

    # 使用新的时间轴分析
    segments = analyze_rwg_timeline(ops, curve_type)
    
    
    if not segments:
        # 如果没有分析到任何段，回退到默认渲染
        pulse_patterns = _detect_pulse_patterns(ops)
        pulse_op_indices = set()
        for p in pulse_patterns:
            pulse_op_indices.update(p['operation_indices'])
        
        for pattern in pulse_patterns:
            start_display = _map_time_to_display(pattern['start_time'], time_mapping)
            end_display = _map_time_to_display(pattern['start_time'] + pattern['duration'], time_mapping)
            width = max(0.5, end_display - start_display)
            
            color, label_prefix = ('lightgreen', 'TTL') if pattern['type'] == 'TTL_PULSE' else ('orange', 'RF')
            label = f"{label_prefix}({pattern['duration']:.1f}μs)"
            
            rect = plt.Rectangle((start_display, y_pos - 0.4), width, 0.8,
                               facecolor=color, alpha=0.3, edgecolor='black', linewidth=1)
            ax.add_patch(rect)
            ax.text(start_display + width/2, y_pos - 0.3, label, ha='center', va='center', 
                   fontsize=8, fontweight='bold', color='black')
        
        for i, pop in enumerate(ops):
            if i not in pulse_op_indices:
                display_pos = _map_time_to_display(pop.timestamp_us, time_mapping)
                op_type = pop.operation.operation_type
                color = _get_operation_color(op_type)
                symbol = _get_operation_symbol_text(op_type)
                _draw_enhanced_operation(ax, pop, display_pos, y_pos, color, symbol)
        return
    
    # 设置曲线颜色
    curve_color = 'blue' if curve_type == "freq" else 'red'
    
    # 建立统一的数值到位置映射
    # 首先收集所有数值范围
    all_values = []
    for segment in segments:
        if segment['type'] == 'static':
            all_values.append(segment['value'])
        elif segment['type'] in ['ramp', 'interpolation'] and segment['coeffs']:
            # 从 ramp/interpolation 的开始和结束值采样
            duration = segment.get('interpolation_duration', segment['end_time'] - segment['start_time'])
            start_val = _evaluate_taylor_series(segment['coeffs'], 0)
            end_val = _evaluate_taylor_series(segment['coeffs'], duration)
            all_values.extend([start_val, end_val])
    
    # 计算数值范围，零点固定在 y_pos
    zero_pos = y_pos  # 零点固定在通道的标称位置
    
    if all_values:
        min_val, max_val = min(all_values), max(all_values)
        # 计算最大偏离零点的距离，确保正负值都能合理显示
        max_abs_val = max(abs(min_val), abs(max_val))
        # 使用固定的显示范围：±0.3 units around y_pos
        scale_factor = 0.3 / max_abs_val if max_abs_val > 0 else 0
    else:
        scale_factor = 0
    
    # 数值到位置的转换函数（考虑 y 轴反转）
    def value_to_pos(val):
        return zero_pos - val * scale_factor  # 负号因为 y 轴被反转
    
    # 绘制零线
    timeline_start = min(seg['start_time'] for seg in segments) if segments else 0
    timeline_end = max(seg['end_time'] for seg in segments) if segments else 0
    if timeline_start < timeline_end:
        start_display = _map_time_to_display(timeline_start, time_mapping)
        end_display = _map_time_to_display(timeline_end, time_mapping)
        ax.plot([start_display, end_display], [zero_pos, zero_pos], 
               color='lightgray', linewidth=1, linestyle=':', alpha=0.7)
    
    # 渲染所有时间段
    for segment in segments:
        start_display = _map_time_to_display(segment['start_time'], time_mapping)
        end_display = _map_time_to_display(segment['end_time'], time_mapping)
        
        if segment['type'] == 'static':
            # 绘制水平直线，使用实际数值位置
            y_value = value_to_pos(segment['value'])
            ax.plot([start_display, end_display], [y_value, y_value], 
                   color=curve_color, linewidth=2, linestyle='-', alpha=0.8)
                   
        elif segment['type'] in ['ramp', 'interpolation'] and segment['coeffs']:
            # 绘制 Taylor 曲线，使用实际数值
            duration = segment.get('interpolation_duration', segment['end_time'] - segment['start_time'])
            num_points = max(50, int(duration * 10))
            t_samples = np.linspace(0, duration, num_points)

            # 计算曲线值
            curve_values = [_evaluate_taylor_series(segment['coeffs'], t) for t in t_samples]

            # 映射到显示时间和位置
            time_points = [segment['start_time'] + t for t in t_samples]
            display_points = [_map_time_to_display(t, time_mapping) for t in time_points]
            position_points = [value_to_pos(val) for val in curve_values]

            # 绘制曲线
            ax.plot(display_points, position_points, color=curve_color, linewidth=3, alpha=0.9)
    
    # 绘制 RF 背景
    rf_segments = [s for s in segments if s.get('rf_on', False)]
    for rf_seg in rf_segments:
        start_display = _map_time_to_display(rf_seg['start_time'], time_mapping)
        end_display = _map_time_to_display(rf_seg['end_time'], time_mapping)
        width = max(0.1, end_display - start_display)
        
        rect = plt.Rectangle((start_display, y_pos - 0.4), width, 0.8,
                           facecolor='orange', alpha=0.15, edgecolor=None)
        ax.add_patch(rect)
    
    # 在曲线显示模式下，不绘制LOAD等准备操作，只显示纯净的曲线
    # 用户只想看到连续的amp/freq变化，而不是这些瞬时的准备操作
    pass


