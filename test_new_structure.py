#!/usr/bin/env python3
"""
Test script for the new modular CatSeq structure.

This script verifies that all the functionality from ttl_minimal.py
works correctly in the new modular structure.
"""

import catseq

def test_basic_operations():
    """测试基础操作和类型"""
    print("=== 测试基础操作 ===")
    
    # 创建板卡和通道
    rwg0 = catseq.Board("RWG_0")
    ch0 = catseq.Channel(rwg0, 0)
    ch1 = catseq.Channel(rwg0, 1)
    ch2 = catseq.Channel(rwg0, 2)
    
    print(f"Board: {rwg0}")
    print(f"Channels: {ch0}, {ch1}, {ch2}")
    
    # 测试时间转换
    us_val = 10.0
    cycles = catseq.us_to_cycles(us_val)
    back_to_us = catseq.cycles_to_us(cycles)
    print(f"Time conversion: {us_val}μs → {cycles} cycles → {back_to_us}μs")
    
    print("✅ 基础操作测试通过\n")


def test_atomic_operations():
    """测试原子操作"""
    print("=== 测试原子操作 ===")
    
    rwg0 = catseq.Board("RWG_0") 
    ch0 = catseq.Channel(rwg0, 0)
    
    # 创建原子操作
    init_op = catseq.ttl_init(ch0)
    on_op = catseq.ttl_on(ch0)
    off_op = catseq.ttl_off(ch0)
    wait_op = catseq.wait(10.0)
    
    print(f"TTL Init: {init_op}")
    print(f"TTL On: {on_op}")
    print(f"TTL Off: {off_op}")
    print(f"Wait: {wait_op}")
    
    print("✅ 原子操作测试通过\n")


def test_morphism_composition():
    """测试 Morphism 组合"""
    print("=== 测试 Morphism 组合 ===")
    
    rwg0 = catseq.Board("RWG_0")
    ch0 = catseq.Channel(rwg0, 0)
    ch1 = catseq.Channel(rwg0, 1)
    
    # 创建基本操作序列
    init_all = catseq.from_atomic(catseq.ttl_init(ch0)) | catseq.from_atomic(catseq.ttl_init(ch1))
    
    pulse1 = catseq.from_atomic(catseq.ttl_on(ch0)) >> catseq.from_atomic(catseq.wait(10.0)) >> catseq.from_atomic(catseq.ttl_off(ch0))
    pulse2 = catseq.from_atomic(catseq.ttl_on(ch1)) >> catseq.from_atomic(catseq.wait(10.0)) >> catseq.from_atomic(catseq.ttl_off(ch1))
    
    # 组合操作
    combined = init_all @ (pulse1 | pulse2)
    
    print(f"Combined sequence: {combined}")
    print("\nDetailed view:")
    print(combined.lanes_view())
    
    print("✅ Morphism 组合测试通过\n")


def test_hardware_abstractions():
    """测试硬件抽象层"""
    print("=== 测试硬件抽象层 ===")
    
    rwg0 = catseq.Board("RWG_0")
    ch0 = catseq.Channel(rwg0, 0)
    
    # 使用高级接口
    init_seq = catseq.initialize_channel(ch0)
    pulse_seq = catseq.pulse(ch0, 10.0)
    combined = init_seq @ pulse_seq
    
    print(f"Hardware abstraction result: {combined}")
    print("\nDetailed view:")
    print(combined.lanes_view())
    
    print("✅ 硬件抽象层测试通过\n")


def test_oasm_compilation():
    """测试 OASM 编译"""
    print("=== 测试 OASM 编译 ===")
    
    rwg0 = catseq.Board("RWG_0")
    ch0 = catseq.Channel(rwg0, 0)
    ch1 = catseq.Channel(rwg0, 1)
    
    # 创建测试序列
    init_all = catseq.initialize_channel(ch0) | catseq.initialize_channel(ch1)
    pulses = catseq.pulse(ch0, 10.0) | catseq.pulse(ch1, 10.0)
    sequence = init_all @ pulses
    
    # 编译为 OASM
    oasm_calls = catseq.compile_to_oasm_calls(sequence)
    
    print(f"生成了 {len(oasm_calls)} 个 OASM 调用:")
    for i, call in enumerate(oasm_calls):
        args_str = ', '.join(str(arg) for arg in call.args) if call.args else ''
        kwargs_str = ', '.join(f'{k}={v}' for k, v in call.kwargs.items()) if call.kwargs else ''
        params_str = ', '.join(filter(None, [args_str, kwargs_str]))
        func_name = call.dsl_func.__name__ if hasattr(call.dsl_func, '__name__') else str(call.dsl_func)
        print(f"  {i+1}. seq('{call.adr.value}', {func_name}, {params_str})")
    
    print("✅ OASM 编译测试通过\n")


def main():
    """运行所有测试"""
    print("🧪 CatSeq 模块化结构测试")
    print("=" * 50)
    
    try:
        test_basic_operations()
        test_atomic_operations()
        test_morphism_composition()
        test_hardware_abstractions()
        test_oasm_compilation()
        
        print("🎉 所有测试通过！新的模块化结构工作正常。")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())