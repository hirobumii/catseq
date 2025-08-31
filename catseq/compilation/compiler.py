"""
OASM compiler for converting Morphism objects to OASM DSL calls.

This module provides the compilation logic for translating high-level
Morphism objects into concrete OASM DSL function calls.
"""

from typing import List

from ..types import OperationType
from ..morphism import Morphism
from ..lanes import merge_board_lanes
from .types import OASMAddress, OASMFunction, OASMCall


def compile_to_oasm_calls(morphism) -> List[OASMCall]:
    """将 Morphism 编译为 OASM 调用序列
    
    Args:
        morphism: 要编译的 Morphism 对象 (支持mock对象)
        
    Returns:
        OASM 调用序列
    """
    calls: List[OASMCall] = []
    
    # 检查是否是mock对象，如果是，直接使用mock数据
    if hasattr(morphism, '_mock_physical_operations'):
        # 使用mock数据
        physical_operations = morphism._mock_physical_operations
        board = morphism._mock_board
        
        # 将板卡ID映射到 OASMAddress
        try:
            adr = OASMAddress(board.id.lower() if hasattr(board, 'id') else str(board).lower())
        except ValueError:
            adr = OASMAddress.RWG0
        
        # 直接处理物理操作
        _process_physical_operations(calls, adr, physical_operations)
    else:
        # 正常处理真实的Morphism对象
        for board, board_lanes in morphism.lanes_by_board().items():
            physical_lane = merge_board_lanes(board, board_lanes)
            
            # 将板卡ID映射到 OASMAddress
            try:
                adr = OASMAddress(board.id.lower() if hasattr(board, 'id') else str(board).lower())
            except ValueError:
                adr = OASMAddress.RWG0
            
            _process_physical_operations(calls, adr, physical_lane.operations)
    
    return calls


def _process_physical_operations(calls: List[OASMCall], adr: OASMAddress, physical_operations):
    """处理物理操作序列，提取公共逻辑"""
    # 按时间戳分组操作，处理同时操作
    operations_by_timestamp = {}
    for pop in physical_operations:
        timestamp = pop.timestamp_cycles
        if timestamp not in operations_by_timestamp:
            operations_by_timestamp[timestamp] = []
        operations_by_timestamp[timestamp].append(pop.operation)
    
    # 按时间顺序处理每个时间点的操作
    for timestamp in sorted(operations_by_timestamp.keys()):
        ops = operations_by_timestamp[timestamp]
        # 显示绝对时间戳信息
        print(f"  t={timestamp}: {len(ops)} operations: {[f'{op.operation_type.name}-CH{op.channel.local_id}' for op in ops]}")
        
        # 按操作类型分组同时操作
        ops_by_type = {}
        for op in ops:
            op_type = op.operation_type
            if op_type not in ops_by_type:
                ops_by_type[op_type] = []
            ops_by_type[op_type].append(op)
        
        # 处理TTL_INIT操作（单独处理）
        if OperationType.TTL_INIT in ops_by_type:
            type_ops = ops_by_type[OperationType.TTL_INIT]
            mask = 0
            dir_value = 0
            
            for op in type_ops:
                channel_mask = 1 << op.channel.local_id
                mask |= channel_mask
                if op.end_state.value == 1:
                    dir_value |= channel_mask
            
            call = OASMCall(
                adr=adr,
                dsl_func=OASMFunction.TTL_CONFIG,
                args=(mask, dir_value),
                kwargs={}
            )
            calls.append(call)
        
        # 处理TTL状态设置操作（TTL_ON和TTL_OFF可能同时发生）
        if OperationType.TTL_ON in ops_by_type or OperationType.TTL_OFF in ops_by_type:
            mask = 0
            state_value = 0
            
            # 处理所有TTL_ON操作
            if OperationType.TTL_ON in ops_by_type:
                for op in ops_by_type[OperationType.TTL_ON]:
                    channel_mask = 1 << op.channel.local_id
                    mask |= channel_mask
                    state_value |= channel_mask  # 该通道设为HIGH
            
            # 处理所有TTL_OFF操作
            if OperationType.TTL_OFF in ops_by_type:
                for op in ops_by_type[OperationType.TTL_OFF]:
                    channel_mask = 1 << op.channel.local_id
                    mask |= channel_mask
                    # state_value中对应bit保持0 (该通道设为LOW)
            
            if mask > 0:  # 有实际的状态变化
                call = OASMCall(
                    adr=adr,
                    dsl_func=OASMFunction.TTL_SET,
                    args=(mask, state_value),
                    kwargs={}
                )
                calls.append(call)
        
        # 处理其他未知操作类型
        for op_type in ops_by_type:
            if op_type not in [OperationType.TTL_INIT, OperationType.TTL_ON, OperationType.TTL_OFF]:
                print(f"Warning: Unhandled operation type: {op_type}")


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


