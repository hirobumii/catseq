#!/usr/bin/env python3
"""
CatSeq核心系统边界情况测试
测试各种极端情况和异常场景
"""

from dataclasses import dataclass
from catseq.core import (
    State, Channel, HardwareDevice, PhysicsViolationError, CompositionError,
    SystemState, SystemStateBuilder, create_system_state,
    AtomicOperation, Morphism
)


@dataclass(frozen=True)
class TTLState(State):
    active: bool = False

@dataclass(frozen=True)  
class TTLOn(TTLState):
    active: bool = True

@dataclass(frozen=True)
class TTLOff(TTLState):
    active: bool = False


class TTLDevice:
    def __init__(self, name: str):
        self.name = name
    
    def validate_transition(self, from_state: State, to_state: State) -> None:
        pass
    
    def validate_taylor_coefficients(self, freq_coeffs: tuple[float, ...], amp_coeffs: tuple[float, ...]) -> None:
        pass


def test_empty_system_state_error():
    """测试空SystemState的错误处理"""
    print("=== 测试空SystemState错误处理 ===")
    
    try:
        empty_state = SystemState(channel_states={})
        assert False, "应该抛出ValueError"
    except ValueError as e:
        print(f"✓ 空SystemState正确抛出错误: {e}")
    
    try:
        builder = SystemStateBuilder()
        empty_from_builder = builder.build()
        assert False, "应该抛出ValueError"
    except ValueError as e:
        print(f"✓ 空SystemStateBuilder正确抛出错误: {e}")
    
    print()


def test_zero_duration_morphism():
    """测试零时长Morphism"""
    print("=== 测试零时长Morphism ===")
    
    device = TTLDevice("ttl0")
    ttl0 = Channel("ttl0", device)
    
    # 零时长原子操作（瞬间切换）
    instant_op = AtomicOperation(
        channel=ttl0,
        from_state=TTLOff(),
        to_state=TTLOn(),
        duration=0.0,
        hardware_params={}
    )
    
    dom = create_system_state((ttl0, TTLOff()))
    cod = create_system_state((ttl0, TTLOn()))
    
    instant_morphism = Morphism(
        dom=dom,
        cod=cod,
        duration=0.0,
        lanes={ttl0: [instant_op]}
    )
    
    assert instant_morphism.duration == 0.0
    print("✓ 零时长Morphism正确")
    
    # 测试零时长morphism的串行组合
    normal_op = AtomicOperation(ttl0, TTLOn(), TTLOff(), 1.0, {})
    normal_morphism = Morphism(
        dom=create_system_state((ttl0, TTLOn())),
        cod=create_system_state((ttl0, TTLOff())),
        duration=1.0,
        lanes={ttl0: [normal_op]}
    )
    
    combined = instant_morphism @ normal_morphism
    assert combined.duration == 1.0
    print("✓ 零时长morphism串行组合正确")
    
    print()


def test_morphism_validation_errors():
    """测试Morphism验证错误"""
    print("=== 测试Morphism验证错误 ===")
    
    device = TTLDevice("ttl0")
    ttl0 = Channel("ttl0", device)
    
    dom = create_system_state((ttl0, TTLOff()))
    cod = create_system_state((ttl0, TTLOn()))
    
    # 测试：dom/cod不一致
    try:
        wrong_op = AtomicOperation(ttl0, TTLOn(), TTLOff(), 1.0, {})  # 与dom/cod不符
        bad_morphism = Morphism(
            dom=dom,
            cod=cod,
            duration=1.0,
            lanes={ttl0: [wrong_op]}
        )
        assert False, "应该抛出ValueError"
    except ValueError as e:
        print(f"✓ dom/cod不一致错误检查: {e}")
    
    # 测试：时长不一致
    try:
        wrong_duration_op = AtomicOperation(ttl0, TTLOff(), TTLOn(), 2.0, {})
        bad_duration_morphism = Morphism(
            dom=dom,
            cod=cod,
            duration=1.0,  # 与操作时长不符
            lanes={ttl0: [wrong_duration_op]}
        )
        assert False, "应该抛出ValueError"
    except ValueError as e:
        print(f"✓ 时长不一致错误检查: {e}")
    
    # 测试：lane内部状态不连续
    op1 = AtomicOperation(ttl0, TTLOff(), TTLOn(), 0.5, {})
    op2 = AtomicOperation(ttl0, TTLOff(), TTLOn(), 0.5, {})  # from_state应该是TTLOn
    
    try:
        bad_continuity_morphism = Morphism(
            dom=dom,
            cod=cod,
            duration=1.0,
            lanes={ttl0: [op1, op2]}  # 状态不连续
        )
        assert False, "应该抛出ValueError"
    except ValueError as e:
        print(f"✓ lane状态不连续错误检查: {e}")
    
    print()


def test_channel_state_management():
    """测试Channel状态管理"""
    print("=== 测试Channel状态管理 ===")
    
    device = TTLDevice("ttl0")
    ttl0 = Channel("ttl0", device)
    
    # 测试初始状态
    assert ttl0.current_state is None
    
    # 设置状态
    ttl0.set_current_state(TTLOff())
    assert ttl0.current_state == TTLOff()
    
    # 更新状态
    ttl0.set_current_state(TTLOn())
    assert ttl0.current_state == TTLOn()
    
    print("✓ Channel状态管理正确")
    print()


def test_system_state_edge_operations():
    """测试SystemState的边界操作"""
    print("=== 测试SystemState边界操作 ===")
    
    device = TTLDevice("ttl")
    ttl0 = Channel("ttl0", device)
    ttl1 = Channel("ttl1", device)
    
    state = create_system_state((ttl0, TTLOn()))
    
    # 测试获取不存在的通道状态
    try:
        missing_state = state.get_state(ttl1)
        assert False, "应该抛出ValueError"
    except ValueError as e:
        print(f"✓ 获取不存在通道状态错误: {e}")
    
    # 测试移除不存在的通道
    unchanged = state.without_channel(ttl1)
    assert unchanged is state  # 应该返回原对象
    
    # 测试移除唯一通道
    try:
        empty = state.without_channel(ttl0)
        assert False, "应该抛出ValueError"
    except ValueError as e:
        print(f"✓ 移除唯一通道错误: {e}")
    
    print()


def test_parallel_composition_edge_cases():
    """测试并行组合的边界情况"""
    print("=== 测试并行组合边界情况 ===")
    
    device = TTLDevice("ttl")
    ttl0 = Channel("ttl0", device)
    ttl1 = Channel("ttl1", device)
    
    # 测试相同时长的并行组合（不需要Identity补齐）
    op1 = AtomicOperation(ttl0, TTLOff(), TTLOn(), 1.0, {})
    m1 = Morphism(
        dom=create_system_state((ttl0, TTLOff())),
        cod=create_system_state((ttl0, TTLOn())),
        duration=1.0,
        lanes={ttl0: [op1]}
    )
    
    op2 = AtomicOperation(ttl1, TTLOff(), TTLOn(), 1.0, {})  # 相同时长
    m2 = Morphism(
        dom=create_system_state((ttl1, TTLOff())),
        cod=create_system_state((ttl1, TTLOn())),
        duration=1.0,
        lanes={ttl1: [op2]}
    )
    
    parallel = m1 | m2
    assert parallel.duration == 1.0
    
    # 验证没有添加Identity操作
    assert len(parallel.get_lane_operations(ttl0)) == 1
    assert len(parallel.get_lane_operations(ttl1)) == 1
    
    print("✓ 相同时长并行组合不添加Identity")
    
    # 测试零时长与非零时长的并行组合
    instant_op = AtomicOperation(ttl0, TTLOff(), TTLOn(), 0.0, {})
    instant_m = Morphism(
        dom=create_system_state((ttl0, TTLOff())),
        cod=create_system_state((ttl0, TTLOn())),
        duration=0.0,
        lanes={ttl0: [instant_op]}
    )
    
    zero_parallel = instant_m | m2
    assert zero_parallel.duration == 1.0
    
    # 零时长morphism应该被补齐
    ttl0_ops = zero_parallel.get_lane_operations(ttl0)
    assert len(ttl0_ops) == 2  # instant + identity
    assert ttl0_ops[0].duration == 0.0
    assert ttl0_ops[1].duration == 1.0
    
    print("✓ 零时长morphism并行组合正确")
    print()


def run_edge_case_tests():
    """运行所有边界情况测试"""
    print("CatSeq核心系统边界情况测试")
    print("=" * 60)
    print()
    
    try:
        test_empty_system_state_error()
        test_zero_duration_morphism()
        test_morphism_validation_errors()
        test_channel_state_management()
        test_system_state_edge_operations()
        test_parallel_composition_edge_cases()
        
        print("🎉 所有边界情况测试通过！")
        return True
        
    except Exception as e:
        print(f"❌ 边界测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    run_edge_case_tests()