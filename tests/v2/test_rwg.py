"""测试 CatSeq V2 RWG 操作

验证基于原子操作组合的 RWG API
"""

import sys
sys.path.insert(0, "/home/tosaka/catseq")

import struct

from catseq.types.common import Board, Channel, ChannelType
from catseq.time_utils import us
from catseq.v2.rwg import (
    # 原子操作
    rwg_init,
    set_carrier,
    load_coeffs,
    update_params,
    rf_switch,
    wait,
    # 组合操作
    initialize,
    set_state,
    rf_on,
    rf_off,
    rf_pulse,
    linear_ramp,
    # 状态和数据类型
    RWGUninitialized,
    RWGReady,
    RWGActive,
    StaticWaveform,
    WaveformParams,
    _encode_waveform_params,
    _encode_static_waveforms,
)
from catseq.v2.opcodes import OpCode
from catseq.v2.context import reset_context
from catseq.v2.morphism import parallel, BoundMorphism, OpenMorphism, Morphism


# =============================================================================
# 原子操作测试
# =============================================================================

def test_atomic_rwg_init():
    """测试 rwg_init 原子操作"""
    om = rwg_init()
    assert isinstance(om, OpenMorphism)
    assert om.name == "rwg_init"


def test_atomic_set_carrier():
    """测试 set_carrier 原子操作"""
    om = set_carrier(100.0)
    assert isinstance(om, OpenMorphism)
    assert "100.0MHz" in om.name


def test_atomic_load_coeffs():
    """测试 load_coeffs 原子操作"""
    params = [WaveformParams(sbg_id=0, freq_coeffs=(10.0, 0.1, None, None))]
    om = load_coeffs(params)
    assert isinstance(om, OpenMorphism)


def test_atomic_update_params():
    """测试 update_params 原子操作"""
    waveforms = [StaticWaveform(sbg_id=0, freq=10.0, amp=0.5)]
    om = update_params(waveforms)
    assert isinstance(om, OpenMorphism)


def test_atomic_rf_switch():
    """测试 rf_switch 原子操作"""
    on = rf_switch(True)
    off = rf_switch(False)
    assert isinstance(on, OpenMorphism)
    assert isinstance(off, OpenMorphism)
    assert "on" in on.name
    assert "off" in off.name


def test_atomic_wait():
    """测试 wait 原子操作"""
    om = wait(10 * us)
    assert isinstance(om, OpenMorphism)
    assert "10.0us" in om.name


# =============================================================================
# 组合操作测试
# =============================================================================

def test_composite_initialize():
    """测试 initialize 组合操作"""
    om = initialize(100.0)
    assert isinstance(om, OpenMorphism)
    # 验证是 rwg_init >> set_carrier 的组合
    assert "rwg_init" in om.name
    assert "set_carrier" in om.name


def test_composite_set_state():
    """测试 set_state 组合操作"""
    targets = [StaticWaveform(sbg_id=0, freq=10.0, amp=0.5)]
    om = set_state(targets)
    assert isinstance(om, OpenMorphism)


def test_composite_rf_on_off():
    """测试 rf_on/rf_off 组合操作"""
    on = rf_on()
    off = rf_off()
    assert isinstance(on, OpenMorphism)
    assert isinstance(off, OpenMorphism)


def test_composite_rf_pulse():
    """测试 rf_pulse 组合操作"""
    om = rf_pulse(10 * us)
    assert isinstance(om, OpenMorphism)
    # 验证是 rf_on >> wait >> rf_off 的组合
    assert "rf_on" in om.name
    assert "wait" in om.name
    assert "rf_off" in om.name


def test_composite_linear_ramp():
    """测试 linear_ramp 组合操作"""
    start = [StaticWaveform(sbg_id=0, freq=10.0, amp=0.0)]
    target = [StaticWaveform(sbg_id=0, freq=20.0, amp=1.0)]
    om = linear_ramp(start, target, 10 * us)
    assert isinstance(om, OpenMorphism)


# =============================================================================
# 组合链测试
# =============================================================================

def test_composition_chain():
    """测试完整的组合链"""
    # 完整的 RWG 操作序列
    seq = (
        initialize(100.0)
        >> set_state([StaticWaveform(sbg_id=0, freq=10.0, amp=0.5)])
        >> rf_on()
        >> wait(10 * us)
        >> rf_off()
    )
    assert isinstance(seq, OpenMorphism)


def test_linear_ramp_with_set_state():
    """测试 set_state >> linear_ramp 组合"""
    start = [StaticWaveform(sbg_id=0, freq=10.0, amp=0.5)]
    target = [StaticWaveform(sbg_id=0, freq=20.0, amp=1.0)]

    seq = set_state(start) >> linear_ramp(start, target, 10 * us)
    assert isinstance(seq, OpenMorphism)


# =============================================================================
# 绑定和物化测试
# =============================================================================

def test_bind_to_channel():
    """测试绑定到通道"""
    reset_context()
    ch = Channel(Board("RWG_0"), 0, ChannelType.RWG)

    om = initialize(100.0)
    bound = om(ch)

    assert isinstance(bound, BoundMorphism)
    assert ch in bound.channels


def test_materialize_to_morphism():
    """测试物化为 Morphism"""
    reset_context()
    ch = Channel(Board("RWG_0"), 0, ChannelType.RWG)

    bound = initialize(100.0)(ch)
    result = bound({ch: RWGUninitialized()})

    assert isinstance(result, Morphism)
    assert ch in result.end_states


# =============================================================================
# 并行组合测试
# =============================================================================

def test_parallel_rwg_channels():
    """测试多通道并行"""
    reset_context()
    ch0 = Channel(Board("RWG_0"), 0, ChannelType.RWG)
    ch1 = Channel(Board("RWG_0"), 1, ChannelType.RWG)

    combined = parallel({
        ch0: initialize(100.0) >> rf_pulse(10 * us),
        ch1: initialize(200.0) >> rf_pulse(20 * us),
    })

    assert isinstance(combined, BoundMorphism)
    assert combined.channels == {ch0, ch1}


def test_bound_morphism_parallel():
    """测试 BoundMorphism | BoundMorphism"""
    reset_context()
    ch0 = Channel(Board("RWG_0"), 0, ChannelType.RWG)
    ch1 = Channel(Board("RWG_0"), 1, ChannelType.RWG)

    bound0 = rf_on()(ch0)
    bound1 = rf_off()(ch1)

    combined = bound0 | bound1
    assert isinstance(combined, BoundMorphism)
    assert combined.channels == {ch0, ch1}


def test_bound_morphism_sequence():
    """测试 BoundMorphism >> BoundMorphism"""
    reset_context()
    ch = Channel(Board("RWG_0"), 0, ChannelType.RWG)

    bound1 = rf_on()(ch)
    bound2 = rf_off()(ch)

    seq = bound1 >> bound2
    assert isinstance(seq, BoundMorphism)


# =============================================================================
# OpCode 和编码测试
# =============================================================================

def test_opcode_values():
    """验证 RWG OpCode 值"""
    assert OpCode.RWG_INIT == 0x0200
    assert OpCode.RWG_SET_CARRIER == 0x0201
    assert OpCode.RWG_LOAD_COEFFS == 0x0202
    assert OpCode.RWG_UPDATE_PARAMS == 0x0203
    assert OpCode.RWG_RF_SWITCH == 0x0204


def test_encode_static_waveforms():
    """测试静态波形编码"""
    waveforms = [
        StaticWaveform(sbg_id=0, freq=10.0, amp=0.5, phase=0.0),
        StaticWaveform(sbg_id=1, freq=20.0, amp=1.0, phase=3.14),
    ]
    encoded = _encode_static_waveforms(waveforms)
    count = struct.unpack('<B', encoded[:1])[0]
    assert count == 2


def test_encode_waveform_params():
    """测试波形参数编码"""
    params = [
        WaveformParams(
            sbg_id=0,
            freq_coeffs=(10.0, 0.1, None, None),
            amp_coeffs=(0.5, 0.01, None, None),
            initial_phase=0.0,
            phase_reset=True,
        )
    ]
    encoded = _encode_waveform_params(params)
    count = struct.unpack('<B', encoded[:1])[0]
    assert count == 1


# =============================================================================
# 状态兼容性测试
# =============================================================================

def test_hardware_state_compatibility():
    """测试 RWG 硬件状态兼容性检查"""
    uninit = RWGUninitialized()
    ready = RWGReady(carrier_freq=100.0)
    active = RWGActive(carrier_freq=100.0, rf_on=False)

    assert uninit.is_compatible_with(RWGUninitialized())
    assert uninit.is_compatible_with(RWGReady(carrier_freq=200.0))
    assert ready.is_compatible_with(RWGReady(carrier_freq=200.0))
    assert ready.is_compatible_with(RWGActive(carrier_freq=100.0))
    assert active.is_compatible_with(RWGReady(carrier_freq=100.0))
    assert active.is_compatible_with(RWGActive(carrier_freq=100.0, rf_on=True))


def test_rwg_active_state_snapshot():
    """测试 RWGActive 状态快照"""
    snapshot = (
        StaticWaveform(sbg_id=0, freq=10.0, amp=0.5),
        StaticWaveform(sbg_id=1, freq=20.0, amp=1.0),
    )
    active = RWGActive(carrier_freq=100.0, rf_on=True, snapshot=snapshot)

    assert active.carrier_freq == 100.0
    assert active.rf_on is True
    assert len(active.snapshot) == 2


# =============================================================================
# 模版复用测试
# =============================================================================

def test_template_reuse():
    """测试 OpenMorphism 模版复用"""
    reset_context()
    ch0 = Channel(Board("RWG_0"), 0, ChannelType.RWG)
    ch1 = Channel(Board("RWG_0"), 1, ChannelType.RWG)

    template = rf_pulse(10 * us)

    bound0 = template(ch0)
    bound1 = template(ch1)

    assert isinstance(bound0, BoundMorphism)
    assert isinstance(bound1, BoundMorphism)
    assert bound0.channels == {ch0}
    assert bound1.channels == {ch1}


if __name__ == "__main__":
    print("运行 V2 RWG 测试...")

    # 原子操作
    test_atomic_rwg_init()
    print("✓ test_atomic_rwg_init")
    test_atomic_set_carrier()
    print("✓ test_atomic_set_carrier")
    test_atomic_load_coeffs()
    print("✓ test_atomic_load_coeffs")
    test_atomic_update_params()
    print("✓ test_atomic_update_params")
    test_atomic_rf_switch()
    print("✓ test_atomic_rf_switch")
    test_atomic_wait()
    print("✓ test_atomic_wait")

    # 组合操作
    test_composite_initialize()
    print("✓ test_composite_initialize")
    test_composite_set_state()
    print("✓ test_composite_set_state")
    test_composite_rf_on_off()
    print("✓ test_composite_rf_on_off")
    test_composite_rf_pulse()
    print("✓ test_composite_rf_pulse")
    test_composite_linear_ramp()
    print("✓ test_composite_linear_ramp")

    # 组合链
    test_composition_chain()
    print("✓ test_composition_chain")
    test_linear_ramp_with_set_state()
    print("✓ test_linear_ramp_with_set_state")

    # 绑定和物化
    test_bind_to_channel()
    print("✓ test_bind_to_channel")
    test_materialize_to_morphism()
    print("✓ test_materialize_to_morphism")

    # 并行组合
    test_parallel_rwg_channels()
    print("✓ test_parallel_rwg_channels")
    test_bound_morphism_parallel()
    print("✓ test_bound_morphism_parallel")
    test_bound_morphism_sequence()
    print("✓ test_bound_morphism_sequence")

    # OpCode 和编码
    test_opcode_values()
    print("✓ test_opcode_values")
    test_encode_static_waveforms()
    print("✓ test_encode_static_waveforms")
    test_encode_waveform_params()
    print("✓ test_encode_waveform_params")

    # 状态兼容性
    test_hardware_state_compatibility()
    print("✓ test_hardware_state_compatibility")
    test_rwg_active_state_snapshot()
    print("✓ test_rwg_active_state_snapshot")

    # 模版复用
    test_template_reuse()
    print("✓ test_template_reuse")

    print("\n所有 RWG 测试通过!")
