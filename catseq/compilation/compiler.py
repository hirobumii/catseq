"""
OASM compiler for converting Morphism objects to OASM DSL calls.

This module provides the compilation logic for translating high-level
Morphism objects into concrete OASM DSL function calls.
"""

from typing import List, Dict, Callable

from ..types.common import OperationType
from ..lanes import merge_board_lanes
from .types import OASMAddress, OASMFunction, OASMCall
from .functions import ttl_config, ttl_set, wait_us

# Import OASM modules for actual assembly generation
try:
    from oasm.rtmq2.intf import sim_intf
    from oasm.rtmq2 import assembler, disassembler
    from oasm.dev.main import C_MAIN, run_cfg
    from oasm.dev.rwg import C_RWG, rwg
    OASM_AVAILABLE = True
except ImportError as e:
    print(f"Warning: OASM modules not available: {e}")
    OASM_AVAILABLE = False

# Map OASMFunction enum members to actual OASM DSL functions
OASM_FUNCTION_MAP: Dict[OASMFunction, Callable] = {
    OASMFunction.TTL_CONFIG: ttl_config,
    OASMFunction.TTL_SET: ttl_set,
    OASMFunction.WAIT_US: wait_us,
}


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
        # 使用mock数据 - 支持多板卡
        physical_operations = morphism._mock_physical_operations
        
        # 按板卡分组物理操作
        operations_by_board = {}
        for pop in physical_operations:
            board = pop.operation.channel.board
            if board not in operations_by_board:
                operations_by_board[board] = []
            operations_by_board[board].append(pop)
        
        # 为每个板卡生成OASM调用
        for board, board_ops in operations_by_board.items():
            # 将板卡ID映射到 OASMAddress
            try:
                adr = OASMAddress(board.id.lower() if hasattr(board, 'id') else str(board).lower())
            except ValueError:
                adr = OASMAddress.RWG0
            
            print(f"\n🔷 处理{board.id}板卡 ({len(board_ops)}个操作):")
            # 处理该板卡的物理操作
            _process_physical_operations(calls, adr, board_ops)
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
    """处理物理操作序列，根据时间戳插入wait调用"""
    # 按时间戳分组操作，处理同时操作
    operations_by_timestamp = {}
    for pop in physical_operations:
        timestamp = pop.timestamp_cycles
        if timestamp not in operations_by_timestamp:
            operations_by_timestamp[timestamp] = []
        operations_by_timestamp[timestamp].append(pop.operation)

    # 跟踪上一个事件的时间，以计算wait时长
    previous_timestamp_cycles = 0
    from ..time_utils import cycles_to_us

    # 按时间顺序处理每个时间点的操作
    for timestamp in sorted(operations_by_timestamp.keys()):
        # 1. 计算并插入WAIT指令
        wait_cycles = timestamp - previous_timestamp_cycles
        if wait_cycles > 0:
            wait_us_val = cycles_to_us(wait_cycles)
            wait_call = OASMCall(
                adr=adr,
                dsl_func=OASMFunction.WAIT_US,
                args=(wait_us_val,),
                kwargs={}
            )
            calls.append(wait_call)

        # 2. 处理当前时间戳的硬件操作
        ops = operations_by_timestamp[timestamp]
        ops_by_type = {}
        for op in ops:
            op_type = op.operation_type
            if op_type not in ops_by_type:
                ops_by_type[op_type] = []
            ops_by_type[op_type].append(op)

        for op_type, type_ops in ops_by_type.items():
            match op_type:
                case OperationType.TTL_INIT:
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
                case OperationType.TTL_ON | OperationType.TTL_OFF:
                    pass
                case _:
                    print(f"Warning: Unhandled operation type: {op_type}")

        if OperationType.TTL_ON in ops_by_type or OperationType.TTL_OFF in ops_by_type:
            mask = 0
            state_value = 0
            if OperationType.TTL_ON in ops_by_type:
                for op in ops_by_type[OperationType.TTL_ON]:
                    channel_mask = 1 << op.channel.local_id
                    mask |= channel_mask
                    state_value |= channel_mask
            if OperationType.TTL_OFF in ops_by_type:
                for op in ops_by_type[OperationType.TTL_OFF]:
                    channel_mask = 1 << op.channel.local_id
                    mask |= channel_mask
            if mask > 0:
                call = OASMCall(
                    adr=adr,
                    dsl_func=OASMFunction.TTL_SET,
                    args=(mask, state_value),
                    kwargs={}
                )
                calls.append(call)
        
        # 3. 更新时间戳
        previous_timestamp_cycles = timestamp


def execute_oasm_calls(calls: List[OASMCall], seq=None):
    """执行 OASM 调用序列并生成实际的 RTMQ 汇编代码
    
    Args:
        calls: OASM 调用序列
        seq: 可选的 OASM assembler 实例，如果提供则生成实际汇编
        
    Returns:
        (success: bool, seq: assembler object or None)
    """
    print("\n--- Executing OASM Calls ---")
    if not calls:
        print("No OASM calls to execute.")
        return True, seq
    
    if seq is not None and OASM_AVAILABLE:
        # 使用提供的 seq 对象生成实际汇编
        print("🔧 Generating actual RTMQ assembly...")
        try:
            for i, call in enumerate(calls):
                # 从映射中获取实际的 OASM 函数
                func = OASM_FUNCTION_MAP.get(call.dsl_func)
                
                if func is None:
                    print(f"Error: OASM function '{call.dsl_func.name}' not found in map.")
                    return False
                
                # 准备打印信息
                args_str = ", ".join(map(str, call.args))
                kwargs_str = ", ".join(f"{k}={v}" for k, v in call.kwargs.items())
                params_str = ", ".join(filter(None, [args_str, kwargs_str]))
                
                print(f"[{i+1:02d}] Board '{call.adr.value}': Calling {func.__name__}({params_str})")
                
                # 直接调用 seq(adr, function, *args, **kwargs)
                seq(call.adr.value, func, *call.args, **call.kwargs)
            
            # 生成汇编代码
            board_names = set(call.adr.value for call in calls)
            for board_name in board_names:
                print(f"\n📋 Generated RTMQ assembly for {board_name}:")
                try:
                    asm_lines = disassembler(core=C_RWG)(seq.asm[board_name])
                    for line in asm_lines:
                        print(f"   {line}")
                except KeyError:
                    print(f"   No assembly generated for {board_name}")
                except Exception as e:
                    print(f"   Assembly generation failed: {e}")
            
            print("\n--- OASM Execution Finished ---")
            return True, seq
            
        except Exception as e:
            import traceback
            print(f"❌ OASM execution with seq failed: {e}")
            traceback.print_exc()
            return False, seq
    elif OASM_AVAILABLE:
        print("⚠️  No seq object provided, falling back to mock execution...")
        success = _execute_oasm_calls_mock(calls)
        return success, None
    else:
        print("⚠️  OASM modules not available, falling back to mock execution...")
        success = _execute_oasm_calls_mock(calls)
        return success, None


def _execute_oasm_calls_mock(calls: List[OASMCall]) -> bool:
    """Mock execution fallback when OASM is not available"""
    try:
        for i, call in enumerate(calls):
            # 从映射中获取实际的 OASM 函数
            func = OASM_FUNCTION_MAP.get(call.dsl_func)
            
            if func is None:
                print(f"Error: OASM function '{call.dsl_func.name}' not found in map.")
                return False
            
            # 准备打印信息
            args_str = ", ".join(map(str, call.args))
            kwargs_str = ", ".join(f"{k}={v}" for k, v in call.kwargs.items())
            params_str = ", ".join(filter(None, [args_str, kwargs_str]))
            
            print(f"[{i+1:02d}] Board '{call.adr.value}': Calling {func.__name__}({params_str})")
            
            # 执行函数
            func(*call.args, **call.kwargs)
            
        return True
    except Exception as e:
        import traceback
        print(f"Mock execution failed: {e}")
        traceback.print_exc()
        return False



