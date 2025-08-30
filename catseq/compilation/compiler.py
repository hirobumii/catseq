"""
OASM compiler for converting Morphism objects to OASM DSL calls.

This module provides the compilation logic for translating high-level
Morphism objects into concrete OASM DSL function calls.
"""

from typing import List, Dict, Tuple

from ..types import Board, OperationType
from ..morphism import Morphism
from ..lanes import merge_board_lanes
from .types import OASMAddress, OASMFunction, OASMCall


def compile_to_oasm_calls(morphism: Morphism) -> List[OASMCall]:
    """将 Morphism 编译为 OASM 调用序列
    
    Args:
        morphism: 要编译的 Morphism 对象
        
    Returns:
        OASM 调用序列
    """
    calls: List[OASMCall] = []
    
    # 按板卡分组并生成调用
    for board, board_lanes in morphism.lanes_by_board().items():
        physical_lane = merge_board_lanes(board, board_lanes)
        
        # 将板卡ID映射到 OASMAddress
        try:
            adr = OASMAddress(board.id.lower() if hasattr(board, 'id') else str(board).lower())
        except ValueError:
            # 如果板卡ID不在枚举中，默认使用 RWG0
            adr = OASMAddress.RWG0
        
        # 分析物理操作，生成 TTL 配置调用
        ttl_events = _extract_ttl_events(physical_lane)
        
        for timestamp, channel_states in ttl_events.items():
            # 计算状态值和掩码
            value, mask = _compute_ttl_config(channel_states)
            
            # 生成 TTL 配置调用 (注意参数顺序：mask, dir)
            call = OASMCall(
                adr=adr,
                dsl_func=OASMFunction.TTL_CONFIG,
                args=(mask, value),  # 修改为 (mask, dir) 顺序
                kwargs={}
            )
            calls.append(call)
    
    return calls


def execute_oasm_calls(calls: List[OASMCall], seq_object) -> bool:
    """执行 OASM 调用序列
    
    Args:
        calls: OASM 调用序列
        seq_object: OASM 序列对象
        
    Returns:
        执行是否成功
    """
    try:
        for call in calls:
            # 调用 seq 对象的方法
            if call.kwargs:
                seq_object(call.adr.value, call.dsl_func.value, *call.args, **call.kwargs)
            else:
                seq_object(call.adr.value, call.dsl_func.value, *call.args)
        return True
    except Exception as e:
        print(f"OASM execution failed: {e}")
        return False


def _extract_ttl_events(physical_lane) -> Dict[int, Dict[int, int]]:
    """从 PhysicalLane 提取 TTL 事件
    
    Args:
        physical_lane: 物理 Lane 对象
        
    Returns:
        时间戳 -> 通道ID -> TTL状态 的映射
    """
    ttl_events: Dict[int, Dict[int, int]] = {}
    
    for pop in physical_lane.operations:
        op = pop.operation
        timestamp = pop.timestamp_cycles
        
        if op.operation_type in [OperationType.TTL_INIT, OperationType.TTL_ON, OperationType.TTL_OFF]:
            if timestamp not in ttl_events:
                ttl_events[timestamp] = {}
            
            # TTL 状态映射
            state_value = 1 if op.end_state.value == 1 else 0
            ttl_events[timestamp][op.channel.local_id] = state_value
    
    return ttl_events


def _compute_ttl_config(channel_states: Dict[int, int]) -> Tuple[int, int]:
    """计算 TTL 配置的 value 和 mask
    
    Args:
        channel_states: 通道ID -> TTL状态 的映射
        
    Returns:
        (value, mask) 元组
    """
    value = 0
    mask = 0
    
    for channel_id, state in channel_states.items():
        mask |= (1 << channel_id)  # 该通道需要配置
        if state:
            value |= (1 << channel_id)  # 该通道设为高电平
    
    return value, mask