#!/usr/bin/env python3
"""
测试 device_types.py 的类型安全实现
"""

from typing import reveal_type
from catseq.device_types import (
    TTLDeviceType, RWGDeviceType,
    TTLChannel, RWGChannel,
    TypedChannelObject, TypedTensorObject,
    create_ttl_channel, create_rwg_channel
)
from catseq.states.ttl import TTLOutputOn, TTLOutputOff, TTLInput
from catseq.states.rwg import RWGReady, RWGActive, RWGStaged, RWGArmed, WaveformParams


def test_ttl_device_type():
    """测试 TTL 设备类型的类型安全"""
    device_type = TTLDeviceType()
    
    # 测试状态验证
    ttl_on = TTLOutputOn()
    ttl_off = TTLOutputOff()
    ttl_input = TTLInput()
    
    # 这些应该成功
    validated_on = device_type.validate_state_type(ttl_on)
    validated_off = device_type.validate_state_type(ttl_off)
    validated_input = device_type.validate_state_type(ttl_input)
    
    # 类型检查器应该推断出正确的类型
    reveal_type(validated_on)  # 应该是 TTLState
    reveal_type(validated_off)  # 应该是 TTLState
    
    # 测试转换验证
    device_type.validate_transition(ttl_on, ttl_off)
    device_type.validate_transition(ttl_off, ttl_input)


def test_rwg_device_type():
    """测试 RWG 设备类型的类型安全"""
    device_type = RWGDeviceType(
        available_sbgs={0, 1, 2},
        max_ramping_order=3,
        frequency_range=(10.0, 1000.0)
    )
    
    # 测试状态验证
    rwg_ready = RWGReady(carrier_freq=100.0)
    rwg_active = RWGActive(waveforms=(
        WaveformParams(sbg_id=0, freq=100.0, amp=0.5, phase=0.0),
    ))
    
    validated_ready = device_type.validate_state_type(rwg_ready)
    validated_active = device_type.validate_state_type(rwg_active)
    
    reveal_type(validated_ready)  # 应该是 RWGState
    reveal_type(validated_active)  # 应该是 RWGState


def test_typed_channels():
    """测试类型安全的通道"""
    ttl_device = TTLDeviceType()
    rwg_device = RWGDeviceType(
        available_sbgs={0, 1},
        max_ramping_order=2,
        frequency_range=(1.0, 100.0)
    )
    
    ttl_channel = TTLChannel(name="ttl0", device_type=ttl_device)
    rwg_channel = RWGChannel(name="rwg0", device_type=rwg_device)
    
    # 测试状态验证
    ttl_state = TTLOutputOn()
    rwg_state = RWGReady(carrier_freq=50.0)
    
    validated_ttl = ttl_channel.validate_state(ttl_state)
    validated_rwg = rwg_channel.validate_state(rwg_state)
    
    reveal_type(validated_ttl)  # 应该是 TTLState
    reveal_type(validated_rwg)  # 应该是 RWGState


def test_typed_channel_objects():
    """测试类型安全的通道对象"""
    ttl_channel = create_ttl_channel("ttl0")
    rwg_channel = create_rwg_channel(
        "rwg0", 
        available_sbgs={0, 1}, 
        max_ramping_order=2,
        frequency_range=(1.0, 100.0)
    )
    
    # 创建类型安全的对象
    ttl_obj = TypedChannelObject(channel=ttl_channel, state=TTLOutputOn())
    rwg_obj = TypedChannelObject(channel=rwg_channel, state=RWGReady(carrier_freq=50.0))
    
    reveal_type(ttl_obj)  # 应该是 TypedChannelObject[TTLState]
    reveal_type(rwg_obj)  # 应该是 TypedChannelObject[RWGState]
    
    # 测试并行组合
    tensor = ttl_obj | rwg_obj
    reveal_type(tensor)  # 应该是 TypedTensorObject


def test_type_errors():
    """测试类型错误情况"""
    ttl_device = TTLDeviceType()
    rwg_device = RWGDeviceType(
        available_sbgs={0},
        max_ramping_order=1,
        frequency_range=(1.0, 100.0)
    )
    
    ttl_channel = TTLChannel(name="ttl0", device_type=ttl_device)
    
    # 这应该在运行时抛出 TypeError
    try:
        rwg_state = RWGReady(carrier_freq=50.0)
        ttl_channel.validate_state(rwg_state)  # 类型不匹配
        print("ERROR: Should have thrown TypeError!")
    except TypeError as e:
        print(f"正确捕获类型错误: {e}")


def test_factory_functions():
    """测试工厂函数的类型推断"""
    ttl_chan = create_ttl_channel("test_ttl")
    rwg_chan = create_rwg_channel(
        "test_rwg",
        available_sbgs={0, 1, 2},
        max_ramping_order=3,
        frequency_range=(10.0, 1000.0)
    )
    
    reveal_type(ttl_chan)  # 应该是 TTLChannel
    reveal_type(rwg_chan)  # 应该是 RWGChannel
    
    # 测试工厂函数创建的通道可以正确验证状态
    ttl_state = ttl_chan.validate_state(TTLOutputOn())
    rwg_state = rwg_chan.validate_state(RWGReady(carrier_freq=100.0))
    
    reveal_type(ttl_state)  # 应该是 TTLState
    reveal_type(rwg_state)  # 应该是 RWGState


if __name__ == "__main__":
    print("运行类型安全测试...")
    test_ttl_device_type()
    test_rwg_device_type()
    test_typed_channels()
    test_typed_channel_objects()
    test_type_errors()
    test_factory_functions()
    print("✅ 所有测试完成!")