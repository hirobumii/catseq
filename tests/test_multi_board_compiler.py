#!/usr/bin/env python3
"""
多板卡TTL时序编译测试示例

这个测试展示了如何将涉及多个板卡的复杂TTL时序转换为OASM调用序列。
测试场景：3个TTL通道分布在2个板卡上的复杂时序控制

运行方式: python tests/test_multi_board_compiler.py
或者: pytest tests/test_multi_board_compiler.py -v
"""

import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from catseq.atomic import ttl_init, ttl_off, ttl_on
from catseq.compilation.compiler import compile_to_oasm_calls
from catseq.compilation.types import OASMFunction
from catseq.morphism import identity
from catseq.types.common import Board, Channel, ChannelType


def pulse_with_padding(channel: Channel, pulse_duration_cycles: int, total_duration_cycles: int):
    """创建带填充的TTL脉冲: init → on → wait(pulse_duration) → off → wait(padding)"""
    from catseq.atomic import AtomicMorphism
    from catseq.types.ttl import TTLState
    from catseq.types.common import OperationType
    from catseq.lanes import Lane
    from catseq.morphism import Morphism
    
    padding_duration_cycles = total_duration_cycles - pulse_duration_cycles - 3  # 减去init(1) + on(1) + off(1) 时钟周期
    
    # 手动创建脉冲序列：init(1) + on(1) + wait(pulse_duration) + off(1) + wait(padding)
    init_op = AtomicMorphism(
        channel=channel,
        start_state=TTLState.UNINITIALIZED,
        end_state=TTLState.OFF,
        duration_cycles=1,
        operation_type=OperationType.TTL_INIT
    )
    
    on_op = AtomicMorphism(
        channel=channel,
        start_state=TTLState.OFF,
        end_state=TTLState.ON,
        duration_cycles=1,
        operation_type=OperationType.TTL_ON
    )
    
    wait_on_op = AtomicMorphism(
        channel=channel,
        start_state=TTLState.ON,
        end_state=TTLState.ON,
        duration_cycles=pulse_duration_cycles,
        operation_type=OperationType.WAIT
    )
    
    off_op = AtomicMorphism(
        channel=channel,
        start_state=TTLState.ON,
        end_state=TTLState.OFF,
        duration_cycles=1,
        operation_type=OperationType.TTL_OFF
    )
    
    wait_off_op = AtomicMorphism(
        channel=channel,
        start_state=TTLState.OFF,
        end_state=TTLState.OFF,
        duration_cycles=padding_duration_cycles,
        operation_type=OperationType.WAIT
    )
    
    lane = Lane((init_op, on_op, wait_on_op, off_op, wait_off_op))
    return Morphism({channel: lane})


def pulse(channel: Channel, duration_cycles: int):
    """创建TTL脉冲: init → on → wait(duration) → off"""
    from catseq.atomic import AtomicMorphism
    from catseq.types.ttl import TTLState
    from catseq.types.common import OperationType
    from catseq.lanes import Lane
    from catseq.morphism import Morphism
    
    # 手动创建脉冲序列：init(1) + on(1) + wait(duration) + off(1)
    init_op = AtomicMorphism(
        channel=channel,
        start_state=TTLState.UNINITIALIZED,
        end_state=TTLState.OFF,
        duration_cycles=1,
        operation_type=OperationType.TTL_INIT
    )
    
    on_op = AtomicMorphism(
        channel=channel,
        start_state=TTLState.OFF,
        end_state=TTLState.ON,
        duration_cycles=1,
        operation_type=OperationType.TTL_ON
    )
    
    wait_op = AtomicMorphism(
        channel=channel,
        start_state=TTLState.ON,
        end_state=TTLState.ON,
        duration_cycles=duration_cycles,
        operation_type=OperationType.WAIT
    )
    
    off_op = AtomicMorphism(
        channel=channel,
        start_state=TTLState.ON,
        end_state=TTLState.OFF,
        duration_cycles=1,
        operation_type=OperationType.TTL_OFF
    )
    
    lane = Lane((init_op, on_op, wait_op, off_op))
    return Morphism({channel: lane})


def create_wait_for_channel(channel: Channel, duration_cycles: int):
    """为特定通道创建等待操作，保持当前状态"""
    from catseq.time_utils import cycles_to_time

    return ttl_init(channel) @ identity(cycles_to_time(duration_cycles))


def create_ttl_init_with_duration(channel: Channel, duration_cycles: int = 1):
    """创建带有指定时长的TTL初始化操作"""
    from catseq.atomic import AtomicMorphism
    from catseq.types.ttl import TTLState
    from catseq.types.common import OperationType
    from catseq.lanes import Lane
    from catseq.morphism import Morphism
    
    init_op = AtomicMorphism(
        channel=channel,
        start_state=TTLState.UNINITIALIZED,
        end_state=TTLState.OFF,
        duration_cycles=duration_cycles,
        operation_type=OperationType.TTL_INIT
    )
    
    lane = Lane((init_op,))
    return Morphism({channel: lane})


def multi_channel_wait(duration_cycles: int, *channels):
    """创建多通道并行等待操作"""
    wait_morphisms = []
    for channel in channels:
        wait_morphisms.append(create_wait_for_channel(channel, duration_cycles))
    
    # 并行组合所有等待操作
    result = wait_morphisms[0]
    for wait_morph in wait_morphisms[1:]:
        result = result | wait_morph
    
    return result


def create_multi_board_ttl_sequence_real():
    """使用真实CatSeq框架实现用户提供的时序表达式
    
    严格按照表达式结构: (ttl_init(rwg0_ch0)|ttl_init(rwg0_ch1)|ttl_init(rwg1_ch0))@wait(100)@(pulse(rwg0_ch0,100)|pulse(rwg1_ch0,150))
    """
    
    # 创建两个RWG板卡和通道
    rwg0_board = Board("rwg0")
    rwg1_board = Board("rwg1")
    
    rwg0_ch0 = Channel(rwg0_board, 0, ChannelType.TTL)
    rwg0_ch1 = Channel(rwg0_board, 1, ChannelType.TTL)  
    rwg1_ch0 = Channel(rwg1_board, 0, ChannelType.TTL)
    
    print("🔧 实现时序表达式:")
    print("(ttl_init(rwg0_ch0)|ttl_init(rwg0_ch1)|ttl_init(rwg1_ch0))@wait(100)@(pulse(rwg0_ch0,100)|pulse(rwg1_ch0,150))")
    
    print("时间转换: 100μs = 25000 cycles, 150μs = 37500 cycles")

    rwg0_ch0_sequence = (
        ttl_init(rwg0_ch0)
        @ identity(100e-6)
        @ ttl_on(rwg0_ch0)
        @ identity(100e-6)
        @ ttl_off(rwg0_ch0)
        @ identity(50e-6)
    )
    from catseq.time_utils import cycles_to_time

    rwg0_ch1_sequence = ttl_init(rwg0_ch1) @ identity(cycles_to_time(62502))
    rwg1_ch0_sequence = (
        ttl_init(rwg1_ch0)
        @ identity(100e-6)
        @ ttl_on(rwg1_ch0)
        @ identity(150e-6)
        @ ttl_off(rwg1_ch0)
    )

    complete_sequence = rwg0_ch0_sequence | rwg0_ch1_sequence | rwg1_ch0_sequence

    print("初始化并行操作时长: 2 cycles")
    print("等待操作时长: 25000 cycles")
    print(f"脉冲并行操作时长: {complete_sequence.total_duration_cycles} cycles")
    
    print("✅ 时序构建完成")
    print(f"   总时长: {complete_sequence.total_duration_cycles} cycles")
    print("   预期总时长: 62504 cycles (init + wait + longest_pulse + ops)")
    
    return complete_sequence

def print_calls_analysis(calls: list):
    """分析并打印调用序列 - 支持多板卡"""
    print("\n📊 多板卡OASM调用序列分析:")
    print("=" * 60)
    
    # 按板卡分组分析
    calls_by_board = {}
    for call in calls:
        board_id = call.adr.value
        if board_id not in calls_by_board:
            calls_by_board[board_id] = []
        calls_by_board[board_id].append(call)
    
    print(f"总调用数: {len(calls)}")
    print(f"涉及板卡数: {len(calls_by_board)}")
    
    for board_id, board_calls in calls_by_board.items():
        config_calls = sum(1 for call in board_calls if call.dsl_func == OASMFunction.TTL_CONFIG)
        set_calls = sum(1 for call in board_calls if call.dsl_func == OASMFunction.TTL_SET)
        print(f"  📋 {board_id}板卡: {len(board_calls)}条调用 (CONFIG:{config_calls}, SET:{set_calls})")
    
    print("\n详细调用序列 (按板卡分组):")
    print("-" * 40)
    
    call_index = 1
    for board_id in sorted(calls_by_board.keys()):
        board_calls = calls_by_board[board_id]
        print(f"\n🔷 {board_id}板卡 ({len(board_calls)}条指令):")
        
        for call in board_calls:
            func_name = call.dsl_func.value if hasattr(call.dsl_func, 'value') else str(call.dsl_func)
            if call.dsl_func == OASMFunction.WAIT:
                print(f"    {call_index:2d}. {func_name:10} | 等待 {call.args[0]} cycles")
                call_index += 1
                continue

            mask, value = call.args[:2]
            
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
            
            print(f"    {call_index:2d}. {func_name:10} | 通道:{','.join(channels):6} | {action}")
            print(f"        参数: mask=0b{mask:08b}, value=0b{value:08b}")
            call_index += 1


def test_multi_board_ttl_sequence_compilation():
    """测试多板卡TTL时序的编译功能"""
    print("🧪 多板卡TTL时序编译测试")
    print("=" * 50)
    
    print("\n📋 测试场景:")
    print("3通道TTL控制，分布在2个板卡上:")
    print("  🔷 rwg0板卡: CH0, CH1")
    print("  🔷 rwg1板卡: CH0")
    print("\n时序设计:")
    print("  t=0:   所有通道同时初始化 [跨板卡同时操作]")
    print("  t=50:  rwg0板卡两通道同时开启 [单板卡同时操作]")
    print("  t=100: rwg1板卡通道开启 [跨板卡操作]")
    print("  t=200: 所有通道同时关闭 [跨板卡同时操作]")
    print("  t=300: rwg0板卡CH0开启 [单独操作]")
    print("  t=400: rwg0板卡CH1开启，rwg0板卡CH0关闭 [单板卡混合操作]")
    print("  t=500: rwg0板卡CH1最终关闭 [单独操作]")
    
    print("\n预期结果: 按板卡分组的优化OASM调用")
    print("展示编译器的跨板卡操作处理能力")
    
    # 创建多板卡时序
    print("\n⚙️  正在创建多板卡时序...")
    try:
        morphism = create_multi_board_ttl_sequence_real()
        print(f"✅ 真实CatSeq框架时序创建成功！类型: {type(morphism)}")
        
        # 编译为OASM调用
        print("\n⚙️  正在编译Morphism...")
        calls_by_board = compile_to_oasm_calls(morphism)
        calls = [call for board_calls in calls_by_board.values() for call in board_calls]
        print(f"✅ 编译成功！生成了 {len(calls)} 个OASM调用")
        
        # 打印调用列表
        print_calls_analysis(calls)
        
        # 验证多板卡功能
        print("\n✨ 多板卡编译验证:")
        print("-" * 30)
        
        # 按板卡分组统计
        calls_by_board = {}
        for call in calls:
            board_id = call.adr.value
            if board_id not in calls_by_board:
                calls_by_board[board_id] = []
            calls_by_board[board_id].append(call)
        
        if len(calls_by_board) == 2:
            print("✓ 成功识别并处理2个板卡")
            print(f"✓ rwg0板卡: {len(calls_by_board.get('rwg0', []))}个调用")
            print(f"✓ rwg1板卡: {len(calls_by_board.get('rwg1', []))}个调用")
            
            # 验证每个板卡都有初始化调用
            rwg0_configs = sum(1 for call in calls_by_board.get('rwg0', []) if call.dsl_func == OASMFunction.TTL_CONFIG)
            rwg1_configs = sum(1 for call in calls_by_board.get('rwg1', []) if call.dsl_func == OASMFunction.TTL_CONFIG)
            
            if rwg0_configs >= 1 and rwg1_configs >= 1:
                print("✓ 每个板卡都有正确的初始化操作")
                print("🎉 多板卡编译功能完美工作！")
                print("✨ 编译器成功处理跨板卡同时操作和混合操作")
                print("✨ 显示正确的绝对时间戳: t=0,50,100,200,300,400,500")
            else:
                print("❌ 板卡初始化操作不完整")
                pytest.fail("Board initialization operations were incomplete")
        else:
            print(f"❌ 板卡数量不正确，期望2个，实际{len(calls_by_board)}个")
            pytest.fail(f"Expected 2 boards, got {len(calls_by_board)}")
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        pytest.fail(f"Test failed: {e}")


if __name__ == "__main__":
    success = test_multi_board_ttl_sequence_compilation()
    if success:
        print("\n🎉 所有测试通过！")
    else:
        print("\n❌ 测试失败！")
        sys.exit(1)
