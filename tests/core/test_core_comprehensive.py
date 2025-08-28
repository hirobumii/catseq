#!/usr/bin/env python3
"""
CatSeq核心系统完整测试
测试所有核心功能和边界条件
"""

from dataclasses import dataclass
from catseq.core import (
    State, Channel, HardwareDevice, PhysicsViolationError, CompositionError,
    SystemState, SystemStateBuilder, create_system_state,
    AtomicOperation, Morphism
)


# 测试状态类
@dataclass(frozen=True)
class TTLState(State):
    active: bool = False

@dataclass(frozen=True)  
class TTLOn(TTLState):
    active: bool = True

@dataclass(frozen=True)
class TTLOff(TTLState):
    active: bool = False


# 测试设备类
class TTLDevice:
    def __init__(self, name: str, allow_transitions: bool = True):
        self.name = name
        self.allow_transitions = allow_transitions
    
    def validate_transition(self, from_state: State, to_state: State) -> None:
        if not self.allow_transitions:
            raise PhysicsViolationError("Transitions not allowed on this device")
    
    def validate_taylor_coefficients(self, freq_coeffs: tuple[float, ...], amp_coeffs: tuple[float, ...]) -> None:
        pass


class RestrictiveDevice:
    """用于测试硬件约束的设备"""
    def validate_transition(self, from_state: State, to_state: State) -> None:
        if isinstance(from_state, TTLOn) and isinstance(to_state, TTLOff):
            raise PhysicsViolationError("Cannot turn off this device")
    
    def validate_taylor_coefficients(self, freq_coeffs: tuple[float, ...], amp_coeffs: tuple[float, ...]) -> None:
        if freq_coeffs and max(freq_coeffs) > 1000:
            raise PhysicsViolationError("Frequency too high")


def test_channel_singleton():
    """测试Channel单例模式"""
    print("=== 测试Channel单例模式 ===")
    
    device = TTLDevice("ttl0")
    
    # 创建同名通道应该返回相同实例
    ch1 = Channel("ttl0", device)
    ch2 = Channel("ttl0", device)
    
    assert ch1 is ch2, "同名通道应该返回相同实例"
    assert ch1.name == "ttl0"
    assert ch1.device is device
    
    # 不同名称应该返回不同实例
    ch3 = Channel("ttl1", device)
    assert ch1 is not ch3
    
    print("✓ Channel单例模式正确")
    print()


def test_system_state_operations():
    """测试SystemState的各种操作"""
    print("=== 测试SystemState操作 ===")
    
    device = TTLDevice("ttl")
    ttl0 = Channel("ttl0", device)
    ttl1 = Channel("ttl1", device)
    
    # 测试基本创建
    state1 = create_system_state((ttl0, TTLOn()), timestamp=1.0)
    state2 = create_system_state((ttl1, TTLOff()), timestamp=2.0)
    
    # 测试merge_with
    merged = state1.merge_with(state2)
    assert len(merged.channels) == 2
    assert merged.timestamp == 2.0  # 取较大的时间戳
    assert merged.get_state(ttl0) == TTLOn()
    assert merged.get_state(ttl1) == TTLOff()
    
    # 测试with_channel_state
    modified = state1.with_channel_state(ttl1, TTLOn())
    assert len(modified.channels) == 2
    assert modified.get_state(ttl0) == TTLOn()
    assert modified.get_state(ttl1) == TTLOn()
    
    # 测试without_channel
    reduced = merged.without_channel(ttl1)
    assert len(reduced.channels) == 1
    assert ttl0 in reduced.channels
    
    # 测试兼容性检查
    state3 = create_system_state((ttl0, TTLOn()))  # 相同状态
    state4 = create_system_state((ttl0, TTLOff())) # 不同状态
    
    assert state1.is_compatible_for_composition(state3), "相同状态应该兼容"
    assert not state1.is_compatible_for_composition(state4), "不同状态应该不兼容"
    
    print("✓ SystemState操作正确")
    print()


def test_system_state_builder():
    """测试SystemStateBuilder"""
    print("=== 测试SystemStateBuilder ===")
    
    device = TTLDevice("ttl")
    ttl0 = Channel("ttl0", device)
    ttl1 = Channel("ttl1", device)
    
    builder = SystemStateBuilder(timestamp=3.0)
    state = (builder
             .add_channel(ttl0, TTLOn())
             .add_channel(ttl1, TTLOff())
             .build())
    
    assert len(state.channels) == 2
    assert state.timestamp == 3.0
    assert state.get_state(ttl0) == TTLOn()
    assert state.get_state(ttl1) == TTLOff()
    
    print("✓ SystemStateBuilder正确")
    print()


def test_atomic_operation_validation():
    """测试AtomicOperation的验证功能"""
    print("=== 测试AtomicOperation验证 ===")
    
    # 测试正常情况
    normal_device = TTLDevice("normal")
    ttl_normal = Channel("ttl_normal", normal_device)
    
    op = AtomicOperation(
        channel=ttl_normal,
        from_state=TTLOff(),
        to_state=TTLOn(),
        duration=1.0,
        hardware_params={}
    )
    
    assert op.duration == 1.0
    assert op.get_write_instruction_count() == 1  # 默认值
    
    # 测试硬件约束违反
    restrictive_device = RestrictiveDevice()
    ttl_restrictive = Channel("ttl_restrictive", restrictive_device)
    
    try:
        bad_op = AtomicOperation(
            channel=ttl_restrictive,
            from_state=TTLOn(),
            to_state=TTLOff(),  # 这个设备不允许关闭
            duration=1.0,
            hardware_params={}
        )
        assert False, "应该抛出PhysicsViolationError"
    except PhysicsViolationError:
        print("✓ 硬件约束验证正确")
    
    # 测试负时长
    try:
        bad_duration_op = AtomicOperation(
            channel=ttl_normal,
            from_state=TTLOff(),
            to_state=TTLOn(),
            duration=-1.0,  # 负时长
            hardware_params={}
        )
        assert False, "应该抛出ValueError"
    except ValueError:
        print("✓ 负时长验证正确")
    
    print()


def test_parallel_composition():
    """测试并行组合"""
    print("=== 测试并行组合 ===")
    
    device = TTLDevice("ttl")
    ttl0 = Channel("ttl0", device)
    ttl1 = Channel("ttl1", device)
    
    # 创建两个独立的morphism
    dom1 = create_system_state((ttl0, TTLOff()))
    cod1 = create_system_state((ttl0, TTLOn()))
    op1 = AtomicOperation(ttl0, TTLOff(), TTLOn(), 1.0, {})
    m1 = Morphism(dom=dom1, cod=cod1, duration=1.0, lanes={ttl0: [op1]})
    
    dom2 = create_system_state((ttl1, TTLOff()))
    cod2 = create_system_state((ttl1, TTLOn()))
    op2 = AtomicOperation(ttl1, TTLOff(), TTLOn(), 2.0, {})  # 更长的时间
    m2 = Morphism(dom=dom2, cod=cod2, duration=2.0, lanes={ttl1: [op2]})
    
    # 并行组合
    parallel = m1 | m2
    
    # 验证结果
    assert parallel.duration == 2.0  # 取较长时间
    assert len(parallel.channels) == 2
    assert ttl0 in parallel.channels
    assert ttl1 in parallel.channels
    
    # 验证短的lane被补齐了Identity
    ttl0_ops = parallel.get_lane_operations(ttl0)
    assert len(ttl0_ops) == 2  # 原操作 + Identity
    assert ttl0_ops[0].duration == 1.0  # 原操作
    assert ttl0_ops[1].duration == 1.0  # Identity补齐
    
    ttl1_ops = parallel.get_lane_operations(ttl1)
    assert len(ttl1_ops) == 1  # 只有原操作
    assert ttl1_ops[0].duration == 2.0
    
    print("✓ 并行组合和Identity自动插入正确")
    print()


def test_composition_errors():
    """测试组合错误情况"""
    print("=== 测试组合错误情况 ===")
    
    device = TTLDevice("ttl")
    ttl0 = Channel("ttl0", device)
    
    # 测试串行组合状态不匹配
    dom1 = create_system_state((ttl0, TTLOff()))
    cod1 = create_system_state((ttl0, TTLOn()))
    op1 = AtomicOperation(ttl0, TTLOff(), TTLOn(), 1.0, {})
    m1 = Morphism(dom=dom1, cod=cod1, duration=1.0, lanes={ttl0: [op1]})
    
    # m2的dom与m1的cod不匹配
    dom2 = create_system_state((ttl0, TTLOff()))  # 应该是TTLOn
    cod2 = create_system_state((ttl0, TTLOff()))
    op2 = AtomicOperation(ttl0, TTLOff(), TTLOff(), 1.0, {})
    m2 = Morphism(dom=dom2, cod=cod2, duration=1.0, lanes={ttl0: [op2]})
    
    try:
        bad_serial = m1 @ m2
        assert False, "应该抛出CompositionError"
    except CompositionError:
        print("✓ 串行组合状态不匹配检查正确")
    
    # 测试并行组合通道冲突
    try:
        bad_parallel = m1 | m1  # 相同通道
        assert False, "应该抛出CompositionError"
    except CompositionError:
        print("✓ 并行组合通道冲突检查正确")
    
    print()


def test_multi_channel_morphism():
    """测试多通道Morphism"""
    print("=== 测试多通道Morphism ===")
    
    device = TTLDevice("ttl")
    ttl0 = Channel("ttl0", device)
    ttl1 = Channel("ttl1", device)
    
    # 创建多通道系统状态
    dom = create_system_state(
        (ttl0, TTLOff()),
        (ttl1, TTLOff())
    )
    cod = create_system_state(
        (ttl0, TTLOn()),
        (ttl1, TTLOn())
    )
    
    # 创建多通道操作
    op0 = AtomicOperation(ttl0, TTLOff(), TTLOn(), 1.0, {})
    op1 = AtomicOperation(ttl1, TTLOff(), TTLOn(), 1.0, {})
    
    multi_morphism = Morphism(
        dom=dom,
        cod=cod,
        duration=1.0,
        lanes={ttl0: [op0], ttl1: [op1]}
    )
    
    assert len(multi_morphism.channels) == 2
    assert multi_morphism.duration == 1.0
    
    # 测试与单通道morphism的组合
    dom2 = create_system_state((ttl0, TTLOn()), (ttl1, TTLOn()))
    cod2 = create_system_state((ttl0, TTLOff()), (ttl1, TTLOn()))  # 只改变ttl0
    op2 = AtomicOperation(ttl0, TTLOn(), TTLOff(), 0.5, {})
    # ttl1保持不变，需要Identity操作
    identity_op = AtomicOperation(ttl1, TTLOn(), TTLOn(), 0.5, {})
    
    partial_change = Morphism(
        dom=dom2,
        cod=cod2,
        duration=0.5,
        lanes={ttl0: [op2], ttl1: [identity_op]}
    )
    
    # 串行组合
    combined = multi_morphism @ partial_change
    assert combined.duration == 1.5
    assert len(combined.channels) == 2
    
    print("✓ 多通道Morphism正确")
    print()


def run_all_tests():
    """运行所有测试"""
    print("CatSeq核心系统完整测试")
    print("=" * 60)
    print()
    
    try:
        test_channel_singleton()
        test_system_state_operations()
        test_system_state_builder()
        test_atomic_operation_validation()
        test_parallel_composition()
        test_composition_errors()
        test_multi_channel_morphism()
        
        print("🎉 所有测试通过！")
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    run_all_tests()