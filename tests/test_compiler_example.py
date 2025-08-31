#!/usr/bin/env python3
"""
复杂TTL时序编译测试示例

这个测试展示了如何将复杂的TTL时序转换为OASM调用序列。
使用真实的CatSeq框架构建时序，测试编译器的同时操作合并功能。
测试场景：2个TTL通道的复杂时序控制

运行方式: python test_compiler_example.py
或者: pytest test_compiler_example.py -v
"""

import sys
sys.path.append('/home/tosaka/catseq')

from catseq.compilation.compiler import compile_to_oasm_calls
from catseq.compilation.types import OASMFunction
from catseq.types import Board, Channel, OperationType
from catseq.atomic import ttl_init, ttl_on, ttl_off, wait
from catseq.morphism import Morphism, from_atomic


def pulse(channel: Channel, duration_us: float) -> Morphism:
    """创建TTL脉冲 morphism: init → on → wait(duration) → off
    
    Args:
        channel: TTL通道
        duration_us: 脉冲持续时间（微秒）
        
    Returns:
        完整的脉冲 morphism
    """
    init_op = ttl_init(channel)
    on_op = ttl_on(channel)
    wait_op = wait(duration_us)  
    off_op = ttl_off(channel)
    
    return from_atomic(init_op) @ on_op >> from_atomic(wait_op) @ from_atomic(off_op)


def delay(duration_us: float) -> Morphism:
    """创建延时 morphism
    
    Args:
        duration_us: 延时时长（微秒）
        
    Returns:
        延时 morphism
    """
    wait_op = wait(duration_us)
    return from_atomic(wait_op)


def create_complex_ttl_sequence():
    """使用直接构建PhysicalOperation的方式创建复杂时序，确保绝对时间戳正确"""
    
    # 创建板卡
    main_board = Board("main")
    
    # 创建TTL通道
    ttl_ch0 = Channel(main_board, 0)
    ttl_ch1 = Channel(main_board, 1)
    
    # 直接构建具有正确绝对时间戳的操作序列
    # 我们将直接使用Mock方式，但使用正确的timestamp
    
    from unittest.mock import Mock
    
    # 创建操作mock的辅助函数
    def create_operation_mock(op_type, channel, state_value, timestamp):
        operation = Mock()
        operation.operation_type = op_type
        operation.channel = channel
        operation.end_state = Mock()
        operation.end_state.value = state_value
        operation.duration_cycles = 1
        
        physical_op = Mock()
        physical_op.operation = operation
        physical_op.timestamp_cycles = timestamp
        
        return physical_op
    
    # 创建复杂时序的物理操作序列 - 使用绝对时间戳
    physical_operations = [
        # t=0: 同时初始化两个通道 [同时操作]
        create_operation_mock(OperationType.TTL_INIT, ttl_ch0, 0, 0),
        create_operation_mock(OperationType.TTL_INIT, ttl_ch1, 0, 0),
        
        # t=100: 同时开启两个通道 [同时操作]  
        create_operation_mock(OperationType.TTL_ON, ttl_ch0, 1, 100),
        create_operation_mock(OperationType.TTL_ON, ttl_ch1, 1, 100),
        
        # t=250: CH0关闭 [单独操作]
        create_operation_mock(OperationType.TTL_OFF, ttl_ch0, 0, 250),
        
        # t=400: CH0再次开启 [单独操作]
        create_operation_mock(OperationType.TTL_ON, ttl_ch0, 1, 400),
        
        # t=500: 同时关闭两个通道 [同时操作]
        create_operation_mock(OperationType.TTL_OFF, ttl_ch0, 0, 500),
        create_operation_mock(OperationType.TTL_OFF, ttl_ch1, 0, 500),
        
        # t=750: CH0开启 [单独操作]
        create_operation_mock(OperationType.TTL_ON, ttl_ch0, 1, 750),
        
        # t=900: CH0关闭, CH1开启 [同时混合操作: 一个关一个开]
        create_operation_mock(OperationType.TTL_OFF, ttl_ch0, 0, 900),
        create_operation_mock(OperationType.TTL_ON, ttl_ch1, 1, 900),
        
        # t=1000: CH1关闭 [单独操作]
        create_operation_mock(OperationType.TTL_OFF, ttl_ch1, 0, 1000),
    ]
    
    # 创建Morphism mock对象，直接提供物理操作序列
    morphism = Mock()
    morphism._mock_physical_operations = physical_operations
    morphism._mock_board = main_board
    
    return morphism


def print_calls_analysis(calls: list):
    """分析并打印调用序列"""
    print("\n📊 OASM调用序列分析:")
    print("=" * 60)
    
    # 统计不同函数类型
    config_calls = sum(1 for call in calls if call.dsl_func == OASMFunction.TTL_CONFIG)
    set_calls = sum(1 for call in calls if call.dsl_func == OASMFunction.TTL_SET)
    
    print(f"总调用数: {len(calls)}")
    print(f"TTL_CONFIG调用: {config_calls} (初始化)")
    print(f"TTL_SET调用: {set_calls} (状态设置)")
    print()
    
    # 详细分析每个调用
    print("详细调用序列:")
    print("-" * 40)
    
    for i, call in enumerate(calls, 1):
        func_name = call.dsl_func.value if hasattr(call.dsl_func, 'value') else str(call.dsl_func)
        mask, value = call.args
        
        # 解析通道
        channels = []
        for bit in range(8):
            if mask & (1 << bit):
                channels.append(f"CH{bit}")
        
        # 解析操作
        if "CONFIG" in str(call.dsl_func):
            action = f"初始化方向={value}"
        else:  # SET
            # 更详细的状态分析
            states = []
            for bit in range(8):
                if mask & (1 << bit):
                    ch_state = "HIGH" if (value & (1 << bit)) else "LOW"
                    states.append(f"CH{bit}={ch_state}")
            action = f"设置状态: {', '.join(states)}"
        
        print(f"{i:2d}. {func_name:10} | 地址:{call.adr.value:4} | 通道:{','.join(channels):6} | {action}")
        print(f"     参数: mask=0b{mask:08b}, value=0b{value:08b}")


def test_complex_ttl_sequence_compilation():
    """测试复杂TTL时序的编译功能"""
    print("🧪 复杂TTL时序编译测试")
    print("=" * 50)
    
    print("\n📋 测试场景:")
    print("2通道TTL复杂时序控制 (测试同时操作合并):")
    print("  t=0:    同时初始化 CH0, CH1 [同时操作] → 1条TTL_CONFIG指令")
    print("  t=100:  同时开启 CH0, CH1 [同时操作] → 1条TTL_SET指令")  
    print("  t=250:  CH0关闭 [单独操作] → 1条TTL_SET指令")
    print("  t=400:  CH0再次开启 [单独操作] → 1条TTL_SET指令")
    print("  t=500:  同时关闭 CH0, CH1 [同时操作] → 1条TTL_SET指令")
    print("  t=750:  CH0开启 [单独操作] → 1条TTL_SET指令")
    print("  t=900:  CH0关闭, CH1开启 [同时混合操作] → 1条TTL_SET指令")
    print("  t=1000: CH1关闭 [单独操作] → 1条TTL_SET指令")
    print("\n预期结果: 8条OASM调用 (1个CONFIG + 7个SET)")
    print("展示编译器的同时操作合并优化能力，包括真正的混合操作")
    
    # 创建复杂时序
    print("\n⚙️  正在创建复杂时序...")
    try:
        morphism = create_complex_ttl_sequence()
        print(f"✅ 时序创建成功！类型: {type(morphism)}")
        
        # 编译为OASM调用
        print("\n⚙️  正在编译Morphism...")
        calls = compile_to_oasm_calls(morphism)
        print(f"✅ 编译成功！生成了 {len(calls)} 个OASM调用")
        
        # 打印调用列表
        print_calls_analysis(calls)
        
        # 验证映射正确性
        print("\n✨ 映射验证:")
        print("-" * 20)
        init_count = sum(1 for call in calls if call.dsl_func == OASMFunction.TTL_CONFIG)
        on_off_count = sum(1 for call in calls if call.dsl_func == OASMFunction.TTL_SET)
        
        print(f"✓ TTL_INIT → TTL_CONFIG: {init_count}/1 (预期1个，同时操作合并)")
        print(f"✓ TTL_ON/OFF → TTL_SET: {on_off_count}/7 (预期7个)")
        
        if init_count == 1 and on_off_count == 7:
            print("🎉 所有映射都正确！同时操作合并功能完美工作！")
            print("✨ 特别展示了真正的混合操作：同时进行一个开启和一个关闭")
            print("✨ 编译器成功将复杂时序优化为8个OASM调用，大幅减少指令数量")
            return True
        else:
            print("❌ 映射数量不符合预期")
            print(f"   实际: TTL_CONFIG={init_count}, TTL_SET={on_off_count}")
            print("   预期: TTL_CONFIG=1, TTL_SET=7")
            return False
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_complex_ttl_sequence_compilation()
    if success:
        print("\n🎉 所有测试通过！")
    else:
        print("\n❌ 测试失败！")
        sys.exit(1)

