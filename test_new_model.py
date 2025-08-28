#!/usr/bin/env python3
"""
测试新的 model_new.py 架构
"""

from catseq.model_new import ChannelObject, TensorObject
from catseq.protocols import Channel, State
from catseq.hardware.ttl import TTLDevice
from catseq.states.ttl import TTLOutputOn, TTLOutputOff
from catseq.states.rwg import RWGReady
from catseq.states.common import Uninitialized

# 创建一个测试用的 RWG 设备类
class TestRWGDevice:
    def __init__(self, name: str):
        self.name = name
        self.available_sbgs = {0, 1, 2, 3}
        self.max_ramping_order = 3
    
    def validate_transition(self, from_state, to_state):
        pass

def test_channel_object():
    """测试 ChannelObject 基本功能"""
    print("=== 测试 ChannelObject ===")
    
    # 创建 channel 和 state
    ttl0 = Channel("TTL_0", TTLDevice)
    ttl_on = TTLOutputOn()
    
    # 创建 ChannelObject
    channel_obj = ChannelObject(channel=ttl0, state=ttl_on)
    
    print(f"ChannelObject: {channel_obj}")
    print(f"Channels: {channel_obj.channels()}")
    print(f"State: {channel_obj.get_state(ttl0)}")
    print()

def test_tensor_object():
    """测试 TensorObject 基本功能"""
    print("=== 测试 TensorObject ===")
    
    # 创建多个 channel 和 state
    ttl0 = Channel("TTL_0", TTLDevice)
    rwg0 = Channel("RWG_0", TestRWGDevice)
    
    ttl_on = TTLOutputOn()
    rwg_ready = RWGReady(carrier_freq=100.0)
    
    # 创建 TensorObject
    tensor_obj = TensorObject(channel_states={
        ttl0: ttl_on,
        rwg0: rwg_ready
    })
    
    print(f"TensorObject: {tensor_obj}")
    print(f"Channels: {tensor_obj.channels()}")
    print(f"TTL state: {tensor_obj.get_state(ttl0)}")
    print(f"RWG state: {tensor_obj.get_state(rwg0)}")
    print()

def test_object_composition():
    """测试 Object 的并行组合"""
    print("=== 测试 Object 并行组合 ===")
    
    # 创建两个 ChannelObject
    ttl0 = Channel("TTL_0", TTLDevice)
    rwg0 = Channel("RWG_0", TestRWGDevice)
    
    channel_obj1 = ChannelObject(channel=ttl0, state=TTLOutputOn())
    channel_obj2 = ChannelObject(channel=rwg0, state=RWGReady(carrier_freq=100.0))
    
    # 并行组合
    composed = channel_obj1 | channel_obj2
    
    print(f"Composed object: {composed}")
    print(f"Type: {type(composed)}")
    print(f"Channels: {composed.channels()}")
    print()
    
    # 测试 ChannelObject | TensorObject
    ttl1 = Channel("TTL_1", TTLDevice)
    channel_obj3 = ChannelObject(channel=ttl1, state=TTLOutputOff())
    
    final_composed = composed | channel_obj3
    print(f"Final composed: {final_composed}")
    print(f"Final channels: {final_composed.channels()}")
    print()

def test_error_cases():
    """测试错误情况"""
    print("=== 测试错误情况 ===")
    
    ttl0 = Channel("TTL_0", TTLDevice)
    
    obj1 = ChannelObject(channel=ttl0, state=TTLOutputOn())
    obj2 = ChannelObject(channel=ttl0, state=TTLOutputOff())  # 同一个 channel
    
    try:
        result = obj1 | obj2  # 应该抛出错误
        print("ERROR: Should have thrown exception!")
    except ValueError as e:
        print(f"正确捕获错误: {e}")
    
    print()

def main():
    """运行所有测试"""
    print("Cat-SEQ 新架构测试")
    print("=" * 50)
    print()
    
    test_channel_object()
    test_tensor_object()  
    test_object_composition()
    test_error_cases()
    
    print("✅ 所有测试完成!")

if __name__ == "__main__":
    main()