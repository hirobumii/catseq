#!/usr/bin/env python3
"""
Compatibility test to ensure new modular structure produces 
identical results to the original ttl_minimal.py implementation.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'legacy'))

import catseq
from ttl_minimal import *


def test_identical_results():
    """确保新结构产生与原结构相同的结果"""
    print("=== 兼容性测试：新结构 vs 原结构 ===")
    
    # 1. 使用新结构
    print("使用新的模块化结构...")
    rwg0_new = catseq.Board("RWG_0")
    ch0_new = catseq.Channel(rwg0_new, 0)
    ch1_new = catseq.Channel(rwg0_new, 1)
    
    init_new = catseq.from_atomic(catseq.ttl_init(ch0_new)) | catseq.from_atomic(catseq.ttl_init(ch1_new))
    pulse1_new = (catseq.from_atomic(catseq.ttl_on(ch0_new)) >> 
                  catseq.from_atomic(catseq.wait(10.0)) >> 
                  catseq.from_atomic(catseq.ttl_off(ch0_new)))
    pulse2_new = (catseq.from_atomic(catseq.ttl_on(ch1_new)) >> 
                  catseq.from_atomic(catseq.wait(10.0)) >> 
                  catseq.from_atomic(catseq.ttl_off(ch1_new)))
    
    combined_new = init_new @ (pulse1_new | pulse2_new)
    calls_new = catseq.compile_to_oasm_calls(combined_new)
    
    # 2. 使用原结构
    print("使用原 ttl_minimal.py 结构...")
    rwg0_old = Board("RWG_0") 
    ch0_old = Channel(rwg0_old, 0)
    ch1_old = Channel(rwg0_old, 1)
    
    init_old = from_atomic(ttl_init(ch0_old)) | from_atomic(ttl_init(ch1_old))
    pulse1_old = (from_atomic(ttl_on(ch0_old)) >> 
                  from_atomic(wait(10.0)) >> 
                  from_atomic(ttl_off(ch0_old)))
    pulse2_old = (from_atomic(ttl_on(ch1_old)) >> 
                  from_atomic(wait(10.0)) >> 
                  from_atomic(ttl_off(ch1_old)))
    
    combined_old = init_old @ (pulse1_old | pulse2_old)
    calls_old = compile_to_oasm_calls(combined_old)
    
    # 3. 比较结果
    print(f"\n新结构生成 {len(calls_new)} 个调用")
    print(f"原结构生成 {len(calls_old)} 个调用")
    
    if len(calls_new) != len(calls_old):
        print("❌ 调用数量不同！")
        return False
    
    print("\n详细对比:")
    all_match = True
    for i, (new_call, old_call) in enumerate(zip(calls_new, calls_old)):
        # 比较调用内容
        new_addr = new_call.adr.value
        old_addr = old_call.adr.value
        new_args = new_call.args
        old_args = old_call.args  
        new_kwargs = new_call.kwargs or {}
        old_kwargs = old_call.kwargs or {}
        
        match = (new_addr == old_addr and 
                new_args == old_args and 
                new_kwargs == old_kwargs)
        
        status = "✅" if match else "❌"
        print(f"  {i+1}. {status} '{new_addr}' vs '{old_addr}', {new_args} vs {old_args}, {new_kwargs} vs {old_kwargs}")
        
        if not match:
            all_match = False
    
    if all_match:
        print("\n🎉 完全兼容！新结构产生与原结构相同的结果。")
        return True
    else:
        print("\n❌ 存在差异，需要进一步检查。")
        return False


def test_performance():
    """简单性能对比"""
    import time
    
    print("\n=== 性能对比 ===")
    
    # 测试新结构
    start = time.time()
    for _ in range(100):
        rwg0 = catseq.Board("RWG_0")
        ch0 = catseq.Channel(rwg0, 0)
        pulse_seq = catseq.pulse(ch0, 10.0)
        calls = catseq.compile_to_oasm_calls(pulse_seq)
    new_time = time.time() - start
    
    # 测试原结构（如果可能的话）
    start = time.time()
    for _ in range(100):
        rwg0 = Board("RWG_0")
        ch0 = Channel(rwg0, 0)
        init_op = from_atomic(ttl_init(ch0))
        on_op = from_atomic(ttl_on(ch0))
        wait_op = from_atomic(wait(10.0))
        off_op = from_atomic(ttl_off(ch0))
        pulse_seq = init_op @ on_op >> wait_op >> off_op
        calls = compile_to_oasm_calls(pulse_seq)
    old_time = time.time() - start
    
    print(f"新结构: {new_time:.4f}s (100次)")
    print(f"原结构: {old_time:.4f}s (100次)")
    print(f"性能比: {new_time/old_time:.2f}x")


def main():
    """运行兼容性测试"""
    try:
        success = test_identical_results()
        test_performance()
        
        if success:
            print("\n✅ 所有兼容性测试通过！")
            return 0
        else:
            print("\n❌ 兼容性测试失败！")
            return 1
            
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())