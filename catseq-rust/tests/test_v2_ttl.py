"""测试 CatSeq V2 TTL 操作

验证完整的 OpenMorphism -> BoundMorphism -> Morphism 流程
"""

import sys
sys.path.insert(0, "/home/tosaka/catseq")

import catseq_rs
from catseq.types.common import Board, Channel, ChannelType
from catseq.time_utils import us
from catseq.v2.ttl import (
    TTLOff,
    TTLOn,
    ttl_on,
    ttl_off,
    ttl_init,
    ttl_pulse,
    wait,
)
from catseq.v2.opcodes import OpCode
from catseq.v2.context import get_context, reset_context
from catseq.v2.morphism import parallel, BoundMorphism, OpenMorphism, Morphism


def test_ttl_on_basic():
    """测试基本的 ttl_on 操作"""
    reset_context()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    # 新 API: ttl_on(ch) -> BoundMorphism
    bound = ttl_on(ch)
    assert isinstance(bound, BoundMorphism)

    # BoundMorphism({ch: state}) -> Morphism
    result = bound({ch: TTLOff()})
    assert isinstance(result, Morphism)
    assert ch in result.end_states


def test_ttl_off_basic():
    """测试基本的 ttl_off 操作"""
    reset_context()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    bound = ttl_off(ch)
    result = bound({ch: TTLOn()})

    assert isinstance(result, Morphism)


def test_ttl_template():
    """测试 OpenMorphism 模版复用"""
    reset_context()
    ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
    ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

    # 创建模版
    template = ttl_pulse(10 * us)
    assert isinstance(template, OpenMorphism)

    # 复用到不同通道
    bound0 = template(ch0)
    bound1 = template(ch1)

    assert isinstance(bound0, BoundMorphism)
    assert isinstance(bound1, BoundMorphism)
    assert bound0.channels == {ch0}
    assert bound1.channels == {ch1}


def test_ttl_sequence():
    """测试 TTL 序列组合 (>>)"""
    reset_context()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    # ttl_on >> wait >> ttl_off (OpenMorphism 级别组合)
    seq = ttl_on() >> wait(10 * us) >> ttl_off()
    assert isinstance(seq, OpenMorphism)

    # 绑定通道
    bound = seq(ch)
    assert isinstance(bound, BoundMorphism)

    # 物化
    result = bound({ch: TTLOff()})
    assert isinstance(result, Morphism)


def test_ttl_pulse():
    """测试 ttl_pulse 便捷函数"""
    reset_context()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    # 直接构建模式
    bound = ttl_pulse(ch, 10 * us)
    assert isinstance(bound, BoundMorphism)

    result = bound({ch: TTLOff()})
    assert isinstance(result, Morphism)


def test_bound_morphism_parallel():
    """测试 BoundMorphism 并行组合 (|)"""
    reset_context()
    ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
    ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

    bound0 = ttl_on(ch0)
    bound1 = ttl_off(ch1)

    # BoundMorphism | BoundMorphism
    combined = bound0 | bound1
    assert isinstance(combined, BoundMorphism)
    assert combined.channels == {ch0, ch1}


def test_bound_morphism_sequence():
    """测试 BoundMorphism 串行组合 (>>)"""
    reset_context()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    bound1 = ttl_on(ch)
    bound2 = wait(ch, 10 * us)
    bound3 = ttl_off(ch)

    # BoundMorphism >> BoundMorphism
    seq = bound1 >> bound2 >> bound3
    assert isinstance(seq, BoundMorphism)


def test_compile_via_node():
    """测试通过 Node 对象编译"""
    ctx = catseq_rs.CompilerContext()

    # 直接创建节点
    # ttl_on/ttl_off 是瞬时操作 (duration=0)
    n1 = ctx.atomic(0, 0, OpCode.TTL_ON, b"")
    n2 = ctx.atomic(0, 2500, OpCode.IDENTITY, b"")
    n3 = ctx.atomic(0, 0, OpCode.TTL_OFF, b"")

    # 组合
    seq = n1 @ n2 @ n3

    # 编译
    events = seq.compile()

    assert len(events) == 3
    # events 格式: [(time, channel_id, opcode, data), ...]
    assert events[0][0] == 0      # time = 0 (ttl_on, 瞬时)
    assert events[0][2] == OpCode.TTL_ON
    assert events[1][0] == 0      # time = 0 (wait 开始，ttl_on 是瞬时的)
    assert events[1][2] == OpCode.IDENTITY
    assert events[2][0] == 2500   # time = 0 + 2500 (ttl_off)
    assert events[2][2] == OpCode.TTL_OFF


def test_opcode_values():
    """验证 OpCode 值"""
    assert OpCode.TTL_ON == 0x0101
    assert OpCode.TTL_OFF == 0x0102
    assert OpCode.IDENTITY == 0x0000


def test_parallel_function():
    """测试 parallel() 函数"""
    reset_context()
    ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
    ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

    # parallel({ch: OpenMorphism}) -> BoundMorphism
    combined = parallel({ch0: ttl_on(), ch1: ttl_pulse(10*us)})
    assert isinstance(combined, BoundMorphism)
    assert combined.channels == {ch0, ch1}


def test_parallel_multi_channel():
    """测试多通道并行组合"""
    reset_context()
    ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
    ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

    # 创建两个通道的脉冲
    pulse0 = ttl_init() >> ttl_on() >> wait(10*us) >> ttl_off()
    pulse1 = ttl_init() >> ttl_on() >> wait(20*us) >> ttl_off()

    # 并行组合
    combined = parallel({ch0: pulse0, ch1: pulse1})

    # 物化
    result = combined({ch0: TTLOff(), ch1: TTLOff()})

    # 验证结果
    assert ch0 in result.end_states
    assert ch1 in result.end_states


if __name__ == "__main__":
    print("运行 V2 TTL 测试...")

    test_ttl_on_basic()
    print("✓ test_ttl_on_basic")

    test_ttl_off_basic()
    print("✓ test_ttl_off_basic")

    test_ttl_template()
    print("✓ test_ttl_template")

    test_ttl_sequence()
    print("✓ test_ttl_sequence")

    test_ttl_pulse()
    print("✓ test_ttl_pulse")

    test_bound_morphism_parallel()
    print("✓ test_bound_morphism_parallel")

    test_bound_morphism_sequence()
    print("✓ test_bound_morphism_sequence")

    test_compile_via_node()
    print("✓ test_compile_via_node")

    test_opcode_values()
    print("✓ test_opcode_values")

    test_parallel_function()
    print("✓ test_parallel_function")

    test_parallel_multi_channel()
    print("✓ test_parallel_multi_channel")

    print("\n所有测试通过!")
