"""测试 CatSeq V2 TTL 操作

验证基于原子操作组合的 TTL API
"""

import sys
sys.path.insert(0, "/home/tosaka/catseq")

import catseq_rs
from catseq.types.common import Board, Channel, ChannelType
from catseq.time_utils import us
from catseq.v2.ttl import (
    # 原子操作
    ttl_init,
    ttl_on,
    ttl_off,
    wait,
    # 组合操作
    ttl_pulse,
    # 状态
    TTLUninitialized,
    TTLOff,
    TTLOn,
)
from catseq.v2.opcodes import OpCode
from catseq.v2.context import get_context, reset_context
from catseq.v2.morphism import parallel, BoundMorphism, OpenMorphism, Morphism


# =============================================================================
# 原子操作测试
# =============================================================================

def test_atomic_ttl_init():
    """测试 ttl_init 原子操作"""
    om = ttl_init()
    assert isinstance(om, OpenMorphism)
    assert om.name == "ttl_init"


def test_atomic_ttl_on():
    """测试 ttl_on 原子操作"""
    om = ttl_on()
    assert isinstance(om, OpenMorphism)
    assert om.name == "ttl_on"


def test_atomic_ttl_off():
    """测试 ttl_off 原子操作"""
    om = ttl_off()
    assert isinstance(om, OpenMorphism)
    assert om.name == "ttl_off"


def test_atomic_wait():
    """测试 wait 原子操作"""
    om = wait(10 * us)
    assert isinstance(om, OpenMorphism)
    assert "10.0us" in om.name


# =============================================================================
# 组合操作测试
# =============================================================================

def test_composite_ttl_pulse():
    """测试 ttl_pulse 组合操作"""
    om = ttl_pulse(10 * us)
    assert isinstance(om, OpenMorphism)
    # 验证是 ttl_on >> wait >> ttl_off 的组合
    assert "ttl_on" in om.name
    assert "wait" in om.name
    assert "ttl_off" in om.name


def test_composition_chain():
    """测试组合链"""
    # ttl_on >> wait >> ttl_off
    seq = ttl_on() >> wait(10 * us) >> ttl_off()
    assert isinstance(seq, OpenMorphism)


def test_composition_with_init():
    """测试带初始化的组合链"""
    seq = ttl_init() >> ttl_on() >> wait(10 * us) >> ttl_off()
    assert isinstance(seq, OpenMorphism)


# =============================================================================
# 绑定和物化测试
# =============================================================================

def test_bind_to_channel():
    """测试绑定到通道"""
    reset_context()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    om = ttl_on()
    bound = om(ch)

    assert isinstance(bound, BoundMorphism)
    assert ch in bound.channels


def test_materialize_to_morphism():
    """测试物化为 Morphism"""
    reset_context()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    bound = ttl_on()(ch)
    result = bound({ch: TTLOff()})

    assert isinstance(result, Morphism)
    assert ch in result.end_states


def test_full_pipeline():
    """测试完整流程: OpenMorphism -> BoundMorphism -> Morphism"""
    reset_context()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    # 组合
    seq = ttl_on() >> wait(10 * us) >> ttl_off()

    # 绑定
    bound = seq(ch)
    assert isinstance(bound, BoundMorphism)

    # 物化
    result = bound({ch: TTLOff()})
    assert isinstance(result, Morphism)


# =============================================================================
# Hybrid API 测试
# =============================================================================
# 并行组合测试
# =============================================================================

def test_parallel_single_channel():
    """测试单通道 parallel（等价于直接绑定）"""
    reset_context()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    # parallel 单通道等价于 op(ch)
    bound = parallel({ch: ttl_pulse(10 * us)})

    assert isinstance(bound, BoundMorphism)
    assert bound.channels == {ch}


def test_parallel_channels():
    """测试多通道并行"""
    reset_context()
    ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
    ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

    combined = parallel({
        ch0: ttl_pulse(10 * us),
        ch1: ttl_pulse(20 * us),
    })

    assert isinstance(combined, BoundMorphism)
    assert combined.channels == {ch0, ch1}


def test_bound_morphism_parallel():
    """测试 BoundMorphism | BoundMorphism"""
    reset_context()
    ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
    ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

    bound0 = ttl_on()(ch0)
    bound1 = ttl_off()(ch1)

    combined = bound0 | bound1
    assert isinstance(combined, BoundMorphism)
    assert combined.channels == {ch0, ch1}


def test_bound_morphism_sequence():
    """测试 BoundMorphism >> BoundMorphism"""
    reset_context()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    bound1 = ttl_on()(ch)
    bound2 = wait(10 * us)(ch)
    bound3 = ttl_off()(ch)

    seq = bound1 >> bound2 >> bound3
    assert isinstance(seq, BoundMorphism)


def test_parallel_multi_channel_materialize():
    """测试多通道并行物化"""
    reset_context()
    ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
    ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

    pulse0 = ttl_init() >> ttl_on() >> wait(10 * us) >> ttl_off()
    pulse1 = ttl_init() >> ttl_on() >> wait(20 * us) >> ttl_off()

    combined = parallel({ch0: pulse0, ch1: pulse1})
    result = combined({ch0: TTLUninitialized(), ch1: TTLUninitialized()})

    assert ch0 in result.end_states
    assert ch1 in result.end_states


# =============================================================================
# OpCode 测试
# =============================================================================

def test_opcode_values():
    """验证 TTL OpCode 值"""
    assert OpCode.TTL_INIT == 0x0100
    assert OpCode.TTL_ON == 0x0101
    assert OpCode.TTL_OFF == 0x0102
    assert OpCode.IDENTITY == 0x0000


# =============================================================================
# 底层 Node 编译测试
# =============================================================================

def test_compile_via_node():
    """测试通过 Node 对象编译"""
    ctx = catseq_rs.CompilerContext()

    n1 = ctx.atomic(0, 0, OpCode.TTL_ON, b"")
    n2 = ctx.atomic(0, 2500, OpCode.IDENTITY, b"")
    n3 = ctx.atomic(0, 0, OpCode.TTL_OFF, b"")

    seq = n1 @ n2 @ n3
    events = seq.compile()

    assert len(events) == 3
    assert events[0][0] == 0
    assert events[0][2] == OpCode.TTL_ON
    assert events[1][0] == 0
    assert events[1][2] == OpCode.IDENTITY
    assert events[2][0] == 2500
    assert events[2][2] == OpCode.TTL_OFF


# =============================================================================
# 状态兼容性测试
# =============================================================================

def test_hardware_state_compatibility():
    """测试 TTL 硬件状态兼容性"""
    on_state = TTLOn()
    off_state = TTLOff()

    assert on_state.is_compatible_with(TTLOn())
    assert on_state.is_compatible_with(TTLOff())
    assert off_state.is_compatible_with(TTLOn())
    assert off_state.is_compatible_with(TTLOff())


# =============================================================================
# 模版复用测试
# =============================================================================

def test_template_reuse():
    """测试 OpenMorphism 模版复用"""
    reset_context()
    ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
    ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

    template = ttl_pulse(10 * us)

    bound0 = template(ch0)
    bound1 = template(ch1)

    assert isinstance(bound0, BoundMorphism)
    assert isinstance(bound1, BoundMorphism)
    assert bound0.channels == {ch0}
    assert bound1.channels == {ch1}


if __name__ == "__main__":
    print("运行 V2 TTL 测试...")

    # 原子操作
    test_atomic_ttl_init()
    print("✓ test_atomic_ttl_init")
    test_atomic_ttl_on()
    print("✓ test_atomic_ttl_on")
    test_atomic_ttl_off()
    print("✓ test_atomic_ttl_off")
    test_atomic_wait()
    print("✓ test_atomic_wait")

    # 组合操作
    test_composite_ttl_pulse()
    print("✓ test_composite_ttl_pulse")
    test_composition_chain()
    print("✓ test_composition_chain")
    test_composition_with_init()
    print("✓ test_composition_with_init")

    # 绑定和物化
    test_bind_to_channel()
    print("✓ test_bind_to_channel")
    test_materialize_to_morphism()
    print("✓ test_materialize_to_morphism")
    test_full_pipeline()
    print("✓ test_full_pipeline")

    # 并行组合
    test_parallel_single_channel()
    print("✓ test_parallel_single_channel")
    test_parallel_channels()
    print("✓ test_parallel_channels")
    test_bound_morphism_parallel()
    print("✓ test_bound_morphism_parallel")
    test_bound_morphism_sequence()
    print("✓ test_bound_morphism_sequence")
    test_parallel_multi_channel_materialize()
    print("✓ test_parallel_multi_channel_materialize")

    # OpCode
    test_opcode_values()
    print("✓ test_opcode_values")

    # Node 编译
    test_compile_via_node()
    print("✓ test_compile_via_node")

    # 状态兼容性
    test_hardware_state_compatibility()
    print("✓ test_hardware_state_compatibility")

    # 模版复用
    test_template_reuse()
    print("✓ test_template_reuse")

    print("\n所有 TTL 测试通过!")
