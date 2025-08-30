#!/usr/bin/env python3
"""
测试新的CatSeq核心系统
"""

from dataclasses import dataclass
from catseq.core import (
    State, Channel, HardwareDevice, PhysicsViolationError,
    SystemState, create_system_state,
    AtomicOperation, Morphism
)


# 创建简单的测试状态
@dataclass(frozen=True)
class TTLState(State):
    active: bool = False

@dataclass(frozen=True)  
class TTLOn(TTLState):
    active: bool = True

@dataclass(frozen=True)
class TTLOff(TTLState):
    active: bool = False


# 创建简单的测试设备
class TTLDevice:
    def __init__(self, name: str):
        self.name = name
    
    def validate_transition(self, from_state: State, to_state: State) -> None:
        # TTL允许任意状态转换
        pass
    
    def validate_taylor_coefficients(self, freq_coeffs: tuple[float, ...], amp_coeffs: tuple[float, ...]) -> None:
        # TTL不使用Taylor系数
        pass


def test_basic_system():
    """测试基础系统组件"""
    print("=== 测试基础系统组件 ===")
    
    # 创建设备和通道
    ttl_device = TTLDevice("ttl0")
    ttl0 = Channel("ttl0", ttl_device)
    
    print(f"创建通道: {ttl0}")
    
    # 创建状态
    off_state = TTLOff()
    on_state = TTLOn()
    
    # 创建系统状态
    initial_state = create_system_state(
        (ttl0, off_state),
        timestamp=0.0
    )
    
    final_state = create_system_state(
        (ttl0, on_state),
        timestamp=1.0
    )
    
    print(f"初始状态: {initial_state}")
    print(f"最终状态: {final_state}")
    print()


def test_atomic_operation():
    """测试原子操作"""
    print("=== 测试原子操作 ===")
    
    ttl_device = TTLDevice("ttl0")
    ttl0 = Channel("ttl0", ttl_device)
    
    # 创建原子操作：TTL切换
    switch_op = AtomicOperation(
        channel=ttl0,
        from_state=TTLOff(),
        to_state=TTLOn(),
        duration=0.0,  # 瞬间切换
        hardware_params={}
    )
    
    print(f"原子操作: {switch_op}")
    print(f"写入指令数: {switch_op.get_write_instruction_count()}")
    print()


def test_simple_morphism():
    """测试简单Morphism"""
    print("=== 测试简单Morphism ===")
    
    ttl_device = TTLDevice("ttl0")
    ttl0 = Channel("ttl0", ttl_device)
    
    # 创建系统状态
    dom = create_system_state((ttl0, TTLOff()), timestamp=0.0)
    cod = create_system_state((ttl0, TTLOn()), timestamp=1.0)
    
    # 创建原子操作
    switch_op = AtomicOperation(
        channel=ttl0,
        from_state=TTLOff(),
        to_state=TTLOn(),
        duration=1.0,
        hardware_params={}
    )
    
    # 创建Morphism
    morphism = Morphism(
        dom=dom,
        cod=cod,
        duration=1.0,
        lanes={ttl0: [switch_op]}
    )
    
    print(f"Morphism: {morphism}")
    print(f"通道数: {len(morphism.channels)}")
    print(f"TTL0操作: {morphism.get_lane_operations(ttl0)}")
    print()


def test_morphism_composition():
    """测试Morphism组合"""
    print("=== 测试Morphism组合 ===")
    
    ttl_device = TTLDevice("ttl0")
    ttl0 = Channel("ttl0", ttl_device)
    
    # 创建第一个morphism: OFF -> ON
    dom1 = create_system_state((ttl0, TTLOff()))
    cod1 = create_system_state((ttl0, TTLOn()))
    
    op1 = AtomicOperation(
        channel=ttl0,
        from_state=TTLOff(),
        to_state=TTLOn(),
        duration=1.0,
        hardware_params={}
    )
    
    m1 = Morphism(dom=dom1, cod=cod1, duration=1.0, lanes={ttl0: [op1]})
    
    # 创建第二个morphism: ON -> OFF
    dom2 = create_system_state((ttl0, TTLOn()))
    cod2 = create_system_state((ttl0, TTLOff()))
    
    op2 = AtomicOperation(
        channel=ttl0,
        from_state=TTLOn(),
        to_state=TTLOff(),
        duration=0.5,
        hardware_params={}
    )
    
    m2 = Morphism(dom=dom2, cod=cod2, duration=0.5, lanes={ttl0: [op2]})
    
    # 测试串行组合
    try:
        composed = m1 @ m2
        print(f"串行组合成功: {composed}")
        print(f"总时长: {composed.duration}")
    except Exception as e:
        print(f"串行组合失败: {e}")
    
    print()


if __name__ == "__main__":
    print("CatSeq核心系统测试")
    print("=" * 50)
    print()
    
    test_basic_system()
    test_atomic_operation()
    test_simple_morphism()  
    test_morphism_composition()
    
    print("✅ 所有测试完成!")