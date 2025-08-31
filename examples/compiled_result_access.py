#!/usr/bin/env python3
"""
演示如何获取和使用编译后的结果

展示多种方式来访问、检查和执行编译后的morphism
"""

from catseq.compiler import compile_morphism, create_executable_morphism
from catseq.protocols import Channel
from catseq.hardware.ttl import TTLDevice
from catseq.morphisms import ttl, common
import inspect


def demo_compiled_result_access():
    """演示各种获取编译结果的方法"""
    
    # 创建一个TTL序列
    ttl0 = Channel("TTL_0", TTLDevice)
    sequence_def = ttl.pulse(duration=10e-6) @ common.hold(duration=5e-6) @ ttl.pulse(duration=10e-6)
    morphism = sequence_def(ttl0)
    
    print("=== 1. 基本编译结果获取 ===")
    
    # 方法1: 获取CompiledMorphism对象
    compiled = compile_morphism(morphism)
    
    print(f"编译结果类型: {type(compiled)}")
    print(f"持续时间: {compiled.duration*1e6:.3f} μs")
    print(f"涉及通道: {[ch.name for ch in compiled.channels]}")
    print(f"是否可调用: {callable(compiled)}")
    print()
    
    print("=== 2. 访问底层函数 ===")
    
    # 访问实际的函数对象
    func = compiled.function
    print(f"函数对象: {func}")
    print(f"函数名称: {func.__name__}")
    print(f"函数文档: {func.__doc__}")
    print(f"函数签名: {inspect.signature(func)}")
    print()
    
    print("=== 3. 创建命名的可执行函数 ===")
    
    # 方法2: 创建命名的可执行函数
    executable = create_executable_morphism(morphism, "my_ttl_sequence")
    
    print(f"可执行函数: {executable}")
    print(f"函数名称: {executable.__name__}")
    print(f"函数文档: {executable.__doc__}")
    print()
    
    print("=== 4. 函数调用方式 ===")
    
    # 不同的调用方式
    print("可用的调用方式:")
    print("1. compiled()           # 直接调用CompiledMorphism")
    print("2. compiled.execute()   # 使用execute方法")
    print("3. compiled.function()  # 直接调用底层函数")
    print("4. executable()         # 调用命名函数")
    print()
    
    print("=== 5. 检查编译结果的内部结构 ===")
    
    # 访问原始morphism
    original = compiled.morphism
    print(f"原始morphism: {original}")
    print(f"原始持续时间: {original.duration*1e6:.3f} μs")
    print(f"lanes数量: {len(original.lanes)}")
    print()
    
    return compiled, executable


def demo_batch_compilation():
    """演示批量编译和结果管理"""
    
    print("=== 批量编译示例 ===")
    
    # 创建多个不同的序列
    ttl0 = Channel("TTL_0", TTLDevice)
    ttl1 = Channel("TTL_1", TTLDevice)
    
    sequences = {
        "short_pulse": ttl.pulse(duration=5e-6)(ttl0),
        "long_pulse": ttl.pulse(duration=20e-6)(ttl0), 
        "double_pulse": (ttl.pulse(duration=5e-6) @ common.hold(duration=10e-6) @ ttl.pulse(duration=5e-6))(ttl0),
        "parallel_pulses": ttl.pulse(duration=10e-6)(ttl0) | ttl.pulse(duration=15e-6)(ttl1)
    }
    
    # 批量编译
    compiled_results = {}
    executable_functions = {}
    
    for name, morphism in sequences.items():
        # 编译
        compiled = compile_morphism(morphism)
        compiled_results[name] = compiled
        
        # 创建可执行函数
        executable = create_executable_morphism(morphism, name)
        executable_functions[name] = executable
        
        print(f"{name:15s}: {compiled.duration*1e6:6.1f} μs, {len(compiled.channels)} 通道")
    
    print(f"\n编译了 {len(compiled_results)} 个序列")
    return compiled_results, executable_functions


def demo_execution_patterns():
    """演示不同的执行模式"""
    
    print("=== 执行模式演示 ===")
    
    # 创建一个简单序列
    ttl0 = Channel("TTL_0", TTLDevice)
    morphism = ttl.pulse(duration=10e-6)(ttl0)
    compiled = compile_morphism(morphism)
    
    print("模拟执行模式 (实际硬件上会执行OASM调用):")
    print()
    
    # 模式1: 直接执行
    print("1. 直接执行模式:")
    print("   try:")
    print("       compiled()  # 执行编译后的morphism")
    print("   except Exception as e:")
    print("       # 处理硬件执行错误")
    print("       pass")
    print()
    
    # 模式2: 与RTMQ播放器配合
    print("2. 与RTMQ播放器配合:")
    executable = create_executable_morphism(morphism, "demo_pulse")
    print(f"   # 创建可执行函数: {executable.__name__}")
    print("   # 在实际硬件上使用:")
    print("   # rwg0_play(demo_pulse)()")
    print()
    
    # 模式3: 批量执行
    print("3. 批量执行模式:")
    print("   for name, compiled in compiled_results.items():")
    print("       print(f'执行 {name}...')")
    print("       compiled()")
    print()
    
    return executable


def demo_inspection_tools():
    """演示编译结果的检查工具"""
    
    print("=== 编译结果检查工具 ===")
    
    # 创建一个复杂的序列
    ttl0 = Channel("TTL_0", TTLDevice)
    ttl1 = Channel("TTL_1", TTLDevice)
    
    # 创建并行脉冲序列
    complex_sequence = ttl.pulse(duration=5e-6)(ttl0) | ttl.pulse(duration=10e-6)(ttl1)
    
    compiled = compile_morphism(complex_sequence)
    
    print("序列分析:")
    print(f"  总持续时间: {compiled.duration*1e6:.3f} μs")
    print(f"  通道数量: {len(compiled.channels)}")
    print(f"  通道列表: {[ch.name for ch in compiled.channels]}")
    print()
    
    print("原始morphism结构:")
    morphism = compiled.morphism
    for channel, primitives in morphism.lanes.items():
        print(f"  {channel.name}:")
        for i, primitive in enumerate(primitives):
            print(f"    {i+1}. {primitive.name}: {primitive.duration*1e6:.3f} μs")
    print()
    
    # 检查函数属性
    func = compiled.function
    print("函数属性:")
    print(f"  __name__: {func.__name__}")
    print(f"  __doc__: {func.__doc__}")
    print(f"  可调用: {callable(func)}")
    print()
    
    return compiled


def main():
    """运行所有演示"""
    print("Cat-SEQ编译结果获取方法演示")
    print("=" * 50)
    print()
    
    # 基本结果获取
    compiled, executable = demo_compiled_result_access()
    
    # 批量编译
    batch_compiled, batch_executable = demo_batch_compilation()
    
    # 执行模式
    demo_execution_patterns()
    
    # 检查工具
    demo_inspection_tools()
    
    print("=== 总结 ===")
    print("获取编译结果的主要方法:")
    print("1. compile_morphism(morphism) -> CompiledMorphism")
    print("2. create_executable_morphism(morphism, name) -> Callable")
    print("3. compiled.function -> 底层函数对象")
    print("4. compiled.morphism -> 原始morphism对象")
    print()
    print("使用方式:")
    print("- compiled() 或 compiled.execute() : 直接执行")
    print("- rwg0_play(executable)() : 在RTMQ硬件上执行")
    print("- 批量管理和执行编译后的序列")


if __name__ == "__main__":
    main()