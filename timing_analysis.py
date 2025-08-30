#!/usr/bin/env python3
"""
详细的时序分析：展示多通道操作的时间轴处理
"""

import catseq

def create_complex_timing_scenario():
    """创建一个复杂的多通道时序场景"""
    print("=== 复杂多通道时序场景分析 ===\n")
    
    rwg0 = catseq.Board("RWG_0")
    laser_trigger = catseq.Channel(rwg0, 0) 
    repump_trigger = catseq.Channel(rwg0, 1)
    imaging_trigger = catseq.Channel(rwg0, 2)
    shutter_control = catseq.Channel(rwg0, 3)
    
    print("场景: 原子冷却实验的激光时序控制")
    print("- 通道0: 冷却激光触发 (laser_trigger)")
    print("- 通道1: 重泵浦激光触发 (repump_trigger)")  
    print("- 通道2: 成像激光触发 (imaging_trigger)")
    print("- 通道3: 光快门控制 (shutter_control)")
    
    # 阶段1: 系统初始化 (所有通道同时初始化到OFF状态)
    init_all = (catseq.initialize_channel(laser_trigger) |
                catseq.initialize_channel(repump_trigger) |
                catseq.initialize_channel(imaging_trigger) |
                catseq.initialize_channel(shutter_control))
    
    # 简化场景：只用两个通道演示时序
    # 阶段2: 两个激光同时开启
    lasers_on = (catseq.set_high(laser_trigger) | 
                 catseq.set_high(repump_trigger))
    
    # 阶段3: 等待10微秒
    pulse_wait = catseq.hold(10.0)
    
    # 阶段4: 两个激光同时关闭
    lasers_off = (catseq.set_low(laser_trigger) | 
                  catseq.set_low(repump_trigger))
    
    # 组合完整序列 (使用自动状态推断)
    complete_experiment = (init_all >> lasers_on >> pulse_wait >> lasers_off)
    
    print(f"\n完整实验序列: {complete_experiment}")
    print(f"总时长: {complete_experiment.total_duration_us:.1f} μs")
    
    print("\n详细时序:")
    for line in complete_experiment.lanes_view().split('\n'):
        if line.strip():
            print(f"  {line}")
    
    return complete_experiment

def analyze_oasm_generation(sequence):
    """分析OASM生成的详细过程"""
    print("\n=== OASM调用生成分析 ===\n")
    
    # 获取板卡分组
    lanes_by_board = sequence.lanes_by_board()
    print("1. 板卡分组:")
    for board, board_lanes in lanes_by_board.items():
        print(f"   板卡 {board.id}: {len(board_lanes)} 个通道")
        for channel, lane in board_lanes.items():
            print(f"     - {channel.global_id}: {len(lane.operations)} 操作")
    
    # 合并为物理Lane
    from catseq.lanes import merge_board_lanes
    for board, board_lanes in lanes_by_board.items():
        print(f"\n2. 板卡 {board.id} 的物理时序合并:")
        physical_lane = merge_board_lanes(board, board_lanes)
        
        print(f"   总共 {len(physical_lane.operations)} 个物理操作:")
        for i, pop in enumerate(physical_lane.operations):
            op = pop.operation
            timestamp_us = pop.timestamp_us
            channel_id = op.channel.local_id if op.channel else 'N/A'
            print(f"     {i+1:2d}. t={timestamp_us:6.1f}μs: 通道{channel_id} {op.operation_type.name} -> {op.end_state.name}")
    
    # 生成OASM调用
    calls = catseq.compile_to_oasm_calls(sequence)
    print(f"\n3. 生成的OASM调用 ({len(calls)}个):")
    
    for i, call in enumerate(calls):
        args_str = ', '.join(str(arg) for arg in call.args) if call.args else ''
        kwargs_str = ', '.join(f'{k}={v}' for k, v in call.kwargs.items()) if call.kwargs else ''
        params_str = ', '.join(filter(None, [args_str, kwargs_str]))
        func_name = call.dsl_func.__name__ if hasattr(call.dsl_func, '__name__') else str(call.dsl_func)
        
        print(f"\n   调用 {i+1}: seq('{call.adr.value}', {func_name}, {params_str})")
        
        if call.kwargs and 'mask' in call.kwargs:
            mask = call.kwargs['mask']
            value = call.args[0] if call.args else 0
            
            # 解析哪些通道被操作
            affected_channels = []
            channel_states = []
            for bit in range(8):  # 检查8个可能的通道
                if mask & (1 << bit):
                    affected_channels.append(bit)
                    state = "HIGH" if (value & (1 << bit)) else "LOW"
                    channel_states.append(f"ch{bit}={state}")
            
            print(f"      -> 操作通道: {affected_channels}")
            print(f"      -> 状态设置: {', '.join(channel_states)}")
            print(f"      -> 二进制: mask=0b{mask:08b}, value=0b{value:08b}")

def demonstrate_timing_precision():
    """演示时序精度的重要性"""
    print("\n=== 时序精度演示 ===\n")
    
    rwg0 = catseq.Board("RWG_0")
    ch0 = catseq.Channel(rwg0, 0)
    ch1 = catseq.Channel(rwg0, 1)
    
    # 创建有微小时间差的操作
    print("测试: 两个通道几乎同时但不完全同时的操作")
    
    # 通道0: 立即开启
    ch0_on = catseq.set_high(ch0)
    
    # 通道1: 稍后0.1微秒开启
    tiny_delay = catseq.hold(0.1) 
    ch1_on = catseq.set_high(ch1)
    
    # 尝试组合（这里会遇到时序不匹配的问题）
    try:
        # 这应该会失败，因为时序不匹配
        almost_simultaneous = ch0_on | (tiny_delay @ ch1_on)
        print("❌ 不应该成功")
    except Exception as e:
        print(f"✅ 正确检测到时序不匹配: {e}")
    
    # 正确的方式：使用串行组合
    print("\n正确的处理方式:")
    sequential = ch0_on >> tiny_delay >> ch1_on
    print(f"串行操作: {sequential}")
    
    calls = catseq.compile_to_oasm_calls(sequential)
    print(f"生成 {len(calls)} 个OASM调用（每个时刻一个）")

def main():
    """运行完整分析"""
    # 创建复杂场景
    experiment_sequence = create_complex_timing_scenario()
    
    # 分析OASM生成
    analyze_oasm_generation(experiment_sequence)
    
    # 时序精度演示
    demonstrate_timing_precision()
    
    print("\n" + "="*70)
    print("📋 总结：同一板卡多通道操作的处理机制")
    print("-" * 70)
    print("1. 🕐 时间戳排序: 所有操作按精确时间戳排序")
    print("2. 🔧 同时操作合并: 相同时刻的操作合并为单个OASM调用")
    print("3. 🎯 位掩码编码: 通过mask和value同时控制多个通道")
    print("4. ⚡ 硬件优化: 最小化OASM调用次数，最大化执行效率")
    print("5. 🔍 精度保证: 微秒级时序精度，确保量子实验的准确性")
    print("="*70)

if __name__ == "__main__":
    main()