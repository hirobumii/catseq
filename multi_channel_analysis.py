#!/usr/bin/env python3
"""
分析当前系统如何处理同一张板卡上多个通道在同一时间的操作
"""

import catseq

def test_simultaneous_operations():
    """测试同时操作多个通道"""
    print("=== 同一板卡多通道同时操作分析 ===\n")
    
    # 创建一个板卡和多个通道
    rwg0 = catseq.Board("RWG_0") 
    ch0 = catseq.Channel(rwg0, 0)  # 通道0
    ch1 = catseq.Channel(rwg0, 1)  # 通道1
    ch2 = catseq.Channel(rwg0, 2)  # 通道2
    
    print("1. 创建3个通道在同一板卡上")
    print(f"   - {ch0}")
    print(f"   - {ch1}") 
    print(f"   - {ch2}")
    
    # 场景1：完全并行的操作
    print("\n2. 场景1：三个通道完全并行初始化")
    init_all = (catseq.initialize_channel(ch0) | 
                catseq.initialize_channel(ch1) |
                catseq.initialize_channel(ch2))
    
    print(f"   并行初始化: {init_all}")
    print("   详细视图:")
    for line in init_all.lanes_view().split('\n'):
        if line.strip():
            print(f"   {line}")
    
    # 编译并查看OASM调用
    calls1 = catseq.compile_to_oasm_calls(init_all)
    print(f"\n   生成了 {len(calls1)} 个OASM调用:")
    for i, call in enumerate(calls1):
        args_str = ', '.join(str(arg) for arg in call.args) if call.args else ''
        kwargs_str = ', '.join(f'{k}={v}' for k, v in call.kwargs.items()) if call.kwargs else ''
        params_str = ', '.join(filter(None, [args_str, kwargs_str]))
        func_name = call.dsl_func.__name__ if hasattr(call.dsl_func, '__name__') else str(call.dsl_func)
        print(f"     {i+1}. seq('{call.adr.value}', {func_name}, {params_str})")
        
        # 解释mask和value
        if call.kwargs and 'mask' in call.kwargs:
            mask = call.kwargs['mask']
            value = call.args[0] if call.args else 0
            print(f"        -> mask=0b{mask:08b} (通道 {[i for i in range(8) if mask & (1<<i)]})")
            print(f"        -> value=0b{value:08b} (高电平通道 {[i for i in range(8) if value & (1<<i)]})")
    
    # 场景2：部分通道并行，然后串行
    print("\n\n3. 场景2：两个通道并行脉冲")
    pulse1 = catseq.pulse(ch0, 10.0)  # ch0: 10μs脉冲
    pulse2 = catseq.pulse(ch1, 10.0)  # ch1: 10μs脉冲 
    parallel_pulses = pulse1 | pulse2
    
    print(f"   并行脉冲: {parallel_pulses}")
    print("   详细视图:")
    for line in parallel_pulses.lanes_view().split('\n'):
        if line.strip():
            print(f"   {line}")
            
    calls2 = catseq.compile_to_oasm_calls(parallel_pulses)
    print(f"\n   生成了 {len(calls2)} 个OASM调用:")
    for i, call in enumerate(calls2):
        args_str = ', '.join(str(arg) for arg in call.args) if call.args else ''
        kwargs_str = ', '.join(f'{k}={v}' for k, v in call.kwargs.items()) if call.kwargs else ''
        params_str = ', '.join(filter(None, [args_str, kwargs_str]))
        func_name = call.dsl_func.__name__ if hasattr(call.dsl_func, '__name__') else str(call.dsl_func)
        print(f"     {i+1}. seq('{call.adr.value}', {func_name}, {params_str})")
        
        if call.kwargs and 'mask' in call.kwargs:
            mask = call.kwargs['mask']
            value = call.args[0] if call.args else 0
            affected_channels = [i for i in range(8) if mask & (1<<i)]
            high_channels = [i for i in range(8) if value & (1<<i)]
            print(f"        -> 操作通道 {affected_channels}, 其中 {high_channels} 设为高电平")

    # 场景3：完整序列
    print("\n\n4. 场景3：完整的多通道控制序列")
    complete_sequence = init_all @ parallel_pulses
    
    print(f"   完整序列: {complete_sequence}")
    print("   详细视图:")
    for line in complete_sequence.lanes_view().split('\n'):
        if line.strip():
            print(f"   {line}")
            
    calls3 = catseq.compile_to_oasm_calls(complete_sequence)
    print(f"\n   生成了 {len(calls3)} 个OASM调用:")
    for i, call in enumerate(calls3):
        args_str = ', '.join(str(arg) for arg in call.args) if call.args else ''
        kwargs_str = ', '.join(f'{k}={v}' for k, v in call.kwargs.items()) if call.kwargs else ''
        params_str = ', '.join(filter(None, [args_str, kwargs_str]))
        func_name = call.dsl_func.__name__ if hasattr(call.dsl_func, '__name__') else str(call.dsl_func)
        print(f"     {i+1}. seq('{call.adr.value}', {func_name}, {params_str})")
        
        if call.kwargs and 'mask' in call.kwargs:
            mask = call.kwargs['mask']
            value = call.args[0] if call.args else 0
            affected_channels = [i for i in range(8) if mask & (1<<i)]
            high_channels = [i for i in range(8) if value & (1<<i)]
            print(f"        -> 操作通道 {affected_channels}, 其中 {high_channels} 设为高电平")


def analyze_merge_strategy():
    """分析合并策略的工作原理"""
    print("\n\n=== 板卡通道合并策略分析 ===\n")
    
    print("当前系统的处理策略:")
    print("1. **时间戳合并**: 所有同一板卡的通道操作按时间戳排序")
    print("2. **位掩码编码**: 同一时刻的多个通道状态合并为单个OASM调用")
    print("3. **硬件优化**: 一个ttl_config调用可以同时配置多个TTL通道")
    
    print("\n具体实现:")
    print("- merge_board_lanes(): 将同一板卡的多个Lane合并为PhysicalLane")
    print("- _extract_ttl_events(): 按时间戳分组TTL状态变化事件") 
    print("- _compute_ttl_config(): 将同时刻的多通道状态编码为value和mask")
    
    print("\n优势:")
    print("✅ 硬件效率: 减少OASM调用次数")
    print("✅ 时序精确: 同时刻的操作真正同时执行")
    print("✅ 资源优化: 一次调用配置多个通道")
    
    print("\n限制:")
    print("⚠️  位数限制: 单个板卡最多支持32个TTL通道(int32)")
    print("⚠️  同步要求: 所有并行操作必须严格同步")


def main():
    """运行分析"""
    test_simultaneous_operations()
    analyze_merge_strategy()
    
    print("\n" + "="*60)
    print("📊 总结: 当前系统通过时间戳合并和位掩码编码")
    print("   高效处理同一板卡上多通道的同时操作")
    print("="*60)


if __name__ == "__main__":
    main()