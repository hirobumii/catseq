"""
清晰展示Device与Channel的不同职责和角色
"""
import pytest
from catseq.core.protocols import Channel, PhysicsViolationError
from catseq.hardware import TTLDevice, RWGDevice
from catseq.states import TTLOn, TTLOff, Uninitialized


def test_device_vs_channel_basic_concepts():
    """
    Device vs Channel: 基本概念区别
    
    Device: 代表物理硬件的约束和验证规则
    Channel: 代表具体的硬件资源标识符
    """
    print("\n=== Device vs Channel: 基本概念 ===")
    
    # 1. Device: 定义硬件类型和约束
    ttl_device = TTLDevice("TTL_CARD_0")  # 物理TTL卡
    rwg_device = RWGDevice("RWG_CARD_0", available_sbgs={0, 1, 2})  # 物理RWG卡
    
    print(f"TTL Device: {ttl_device}")
    print(f"RWG Device: {rwg_device}")
    print(f"RWG可用SBGs: {rwg_device.available_sbgs}")
    
    # 2. Channel: 具体的硬件资源标识
    laser_ttl = Channel("LASER_TRIGGER", ttl_device)     # TTL通道用于激光触发
    gate_ttl = Channel("DETECTION_GATE", ttl_device)     # TTL通道用于探测门控
    
    qubit_rwg = Channel("QUBIT_DRIVE", rwg_device)       # RWG通道用于量子比特控制
    readout_rwg = Channel("READOUT_TONE", rwg_device)    # RWG通道用于读取音调
    
    print(f"Laser TTL Channel: {laser_ttl}")
    print(f"Qubit RWG Channel: {qubit_rwg}")
    
    # 3. 关系验证
    assert laser_ttl.device is ttl_device      # Channel绑定到特定Device
    assert gate_ttl.device is ttl_device       # 多个Channel可以共享同一个Device
    assert qubit_rwg.device is rwg_device
    assert readout_rwg.device is rwg_device
    
    print("✅ Device和Channel概念验证通过")


def test_device_handles_validation():
    """
    Device的职责：硬件约束验证
    """
    print("\n=== Device职责：硬件验证 ===")
    
    # Device定义和执行验证规则
    ttl_device = TTLDevice("TTL_VALIDATOR")
    
    # 1. Device验证状态转换
    print("测试TTL状态转换验证...")
    ttl_device.validate_transition(TTLOff(), TTLOn())      # 应该通过
    ttl_device.validate_transition(TTLOn(), TTLOff())      # 应该通过
    print("✅ TTL状态转换验证通过")
    
    # 2. Device拒绝不合理的转换
    print("测试非法状态转换...")
    with pytest.raises(PhysicsViolationError):
        # TTL Device不应该接受RWG状态
        from catseq.states import RWGReady
        ttl_device.validate_transition(TTLOff(), RWGReady(carrier_freq=5e9))
    print("✅ 非法转换被正确拒绝")
    
    # 3. RWG Device的Taylor系数验证
    rwg_device = RWGDevice("RWG_VALIDATOR", available_sbgs={0}, max_freq_mhz=500.0)
    print("测试RWG Taylor系数验证...")
    
    # 合理的系数应该通过
    rwg_device.validate_taylor_coefficients(
        freq_coeffs=(100.0, 1.0, None, None),  # 100MHz基频 + 1MHz/s斜率
        amp_coeffs=(0.5, None, None, None)      # 恒定0.5振幅
    )
    print("✅ 合理的Taylor系数通过验证")
    
    # 超出限制的系数应该被拒绝
    with pytest.raises(PhysicsViolationError):
        rwg_device.validate_taylor_coefficients(
            freq_coeffs=(600.0, None, None, None),  # 超出max_freq_mhz=500
            amp_coeffs=(0.5, None, None, None)
        )
    print("✅ 超限系数被正确拒绝")


def test_channel_handles_identity():
    """
    Channel的职责：资源标识和单例管理
    """
    print("\n=== Channel职责：资源标识 ===")
    
    ttl_device = TTLDevice("TTL_SHARED")
    
    # 1. Channel单例行为：相同名称 = 相同实例
    ch1 = Channel("SHARED_TTL", ttl_device)
    ch2 = Channel("SHARED_TTL", ttl_device)  # 相同名称
    
    assert ch1 is ch2  # 完全相同的对象
    print(f"相同名称Channel单例验证: {ch1 is ch2}")
    
    # 2. 不同名称 = 不同实例
    ch_a = Channel("TTL_A", ttl_device)
    ch_b = Channel("TTL_B", ttl_device)
    
    assert ch_a is not ch_b  # 不同对象
    assert ch_a.name != ch_b.name  # 不同名称
    assert ch_a.device is ch_b.device  # 但共享Device
    print(f"不同名称Channel区别验证: {ch_a.name} ≠ {ch_b.name}")
    
    # 3. Channel提供对Device能力的访问
    rwg_device = RWGDevice("RWG_ACCESS", available_sbgs={0, 1, 2}, max_ramping_order=3)
    rwg_channel = Channel("RWG_CH", rwg_device)
    
    # 通过Channel访问Device的能力
    available_sbgs = rwg_channel.device.available_sbgs
    max_order = rwg_channel.device.max_ramping_order
    
    print(f"通过Channel访问Device能力: SBGs={available_sbgs}, MaxOrder={max_order}")
    assert available_sbgs == {0, 1, 2}
    assert max_order == 3
    print("✅ Channel提供Device访问验证通过")


def test_real_world_device_channel_usage():
    """
    真实世界中Device和Channel的协作使用
    """
    print("\n=== 真实场景：Device-Channel协作 ===")
    
    # 场景：量子计算实验装置
    print("构建量子计算实验装置...")
    
    # 1. 物理设备定义
    ttl_card = TTLDevice("TTL_CONTROL_CARD")  # TTL控制卡
    rwg_card = RWGDevice(
        name="RWG_SYNTHESIS_CARD",
        available_sbgs={0, 1, 2, 3},     # 4个信号发生器
        max_ramping_order=3,              # 支持3阶Taylor展开
        max_freq_mhz=6000.0,             # 最高6GHz
        amplitude_locked=False            # 允许振幅调制
    )
    
    # 2. 逻辑通道定义 - 每个Channel代表一个具体的实验功能
    laser_pulse = Channel("LASER_PULSE", ttl_card)        # 激光脉冲触发
    readout_gate = Channel("READOUT_GATE", ttl_card)      # 读取门控信号
    
    qubit_xy = Channel("QUBIT_XY_DRIVE", rwg_card)        # 量子比特XY驱动
    qubit_z = Channel("QUBIT_Z_DRIVE", rwg_card)          # 量子比特Z驱动
    cavity_drive = Channel("CAVITY_READOUT", rwg_card)    # 腔体读取驱动
    
    # 3. 验证物理约束通过Device
    print("验证实验操作的物理可行性...")
    
    # TTL操作验证
    for ttl_ch in [laser_pulse, readout_gate]:
        ttl_ch.device.validate_transition(TTLOff(), TTLOn())
        ttl_ch.device.validate_transition(TTLOn(), TTLOff())
    
    # RWG操作验证
    for rwg_ch in [qubit_xy, qubit_z, cavity_drive]:
        # 每个RWG通道都可以进行相同的验证，因为它们共享Device约束
        rwg_ch.device.validate_taylor_coefficients(
            freq_coeffs=(2000.0, 10.0, None, None),  # 2GHz + 10MHz/s ramp
            amp_coeffs=(0.3, 0.05, None, None)        # 0.3基础振幅 + 0.05/s调制
        )
    
    # 4. 验证Channel身份独立性
    print("验证Channel身份独立性...")
    all_channels = [laser_pulse, readout_gate, qubit_xy, qubit_z, cavity_drive]
    
    # 每个Channel有唯一标识
    names = [ch.name for ch in all_channels]
    assert len(set(names)) == len(names)  # 无重复名称
    print(f"所有Channel名称: {names}")
    
    # 但共享相同类型设备的Channel共享约束
    ttl_channels = [laser_pulse, readout_gate]
    rwg_channels = [qubit_xy, qubit_z, cavity_drive]
    
    # 验证TTL channels共享相同Device
    for ttl_ch in ttl_channels:
        assert ttl_ch.device is ttl_card
    
    # 验证RWG channels共享相同Device
    for rwg_ch in rwg_channels:
        assert rwg_ch.device is rwg_card
    
    print("✅ 真实场景Device-Channel协作验证通过")


def test_device_channel_separation_of_concerns():
    """
    验证Device和Channel的关注点分离
    """
    print("\n=== Device-Channel关注点分离 ===")
    
    # Device关注点：物理约束和验证逻辑
    print("Device关注点：硬件物理约束...")
    constraint_device = RWGDevice(
        name="CONSTRAINED_RWG",
        available_sbgs={0, 1},
        max_ramping_order=1,        # 只支持线性变化
        max_freq_mhz=1000.0,        # 1GHz频率限制
        amplitude_locked=True       # 振幅锁定
    )
    
    # Channel关注点：资源标识和访问
    print("Channel关注点：资源标识...")
    control_ch = Channel("CONTROL_CHANNEL", constraint_device)
    measure_ch = Channel("MEASURE_CHANNEL", constraint_device)
    
    # 验证：相同Device约束作用于不同Channel
    for ch in [control_ch, measure_ch]:
        # 每个Channel都受到相同的Device约束
        ch.device.validate_taylor_coefficients(
            freq_coeffs=(500.0, 1.0, None, None),    # 线性变化（符合max_order=1）
            amp_coeffs=(0.5, None, None, None)        # 恒定振幅（符合amplitude_locked）
        )
        
        # 每个Channel都会被相同的Device约束拒绝
        with pytest.raises(PhysicsViolationError):
            ch.device.validate_taylor_coefficients(
                freq_coeffs=(500.0, None, None, None),
                amp_coeffs=(0.5, 0.1, None, None)    # 违反amplitude_locked
            )
    
    # 但Channel标识是独立的
    assert control_ch is not measure_ch
    assert control_ch.name != measure_ch.name
    
    print("✅ 关注点分离验证通过")
    print("  - Device: 负责物理约束验证")
    print("  - Channel: 负责资源标识管理")


if __name__ == "__main__":
    print("Device与Channel角色区别测试")
    print("=" * 50)
    
    test_device_vs_channel_basic_concepts()
    test_device_handles_validation()
    test_channel_handles_identity()
    test_real_world_device_channel_usage()
    test_device_channel_separation_of_concerns()
    
    print("\n✅ 所有Device-Channel区别测试完成!")
    print("\n核心区别总结:")
    print("📋 Device: 物理硬件约束 + 验证规则")
    print("🏷️  Channel: 资源标识符 + 单例管理")
    print("🤝 协作: Channel.device访问 → Device验证")