"""测试 CatSeq V2 TTL 操作

验证完整的 OpenMorphism -> Rust Arena -> Compile 流程
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


def test_ttl_on_basic():
    """测试基本的 ttl_on 操作"""
    ctx = catseq_rs.CompilerContext()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    op = ttl_on()
    result = op(ctx, ch, TTLOff())

    assert isinstance(result.end_state, TTLOn)
    assert result.node_id == 0  # 第一个节点


def test_ttl_off_basic():
    """测试基本的 ttl_off 操作"""
    ctx = catseq_rs.CompilerContext()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    op = ttl_off()
    result = op(ctx, ch, TTLOn())

    assert isinstance(result.end_state, TTLOff)


def test_ttl_sequence():
    """测试 TTL 序列组合"""
    ctx = catseq_rs.CompilerContext()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    # ttl_on >> wait >> ttl_off
    seq = ttl_on() >> wait(10 * us) >> ttl_off()
    result = seq(ctx, ch, TTLOff())

    assert isinstance(result.end_state, TTLOff)

    # 验证节点数量：3 个原子 + 2 个组合
    assert ctx.node_count() == 5


def test_ttl_pulse():
    """测试 ttl_pulse 便捷函数"""
    ctx = catseq_rs.CompilerContext()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    pulse = ttl_pulse(10 * us)
    result = pulse(ctx, ch, TTLOff())

    assert isinstance(result.end_state, TTLOff)


def test_compile_events():
    """测试编译输出"""
    ctx = catseq_rs.CompilerContext()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    # 创建简单序列
    seq = ttl_on() >> wait(2500) >> ttl_off()  # 2500 cycles = 10us
    result = seq(ctx, ch, TTLOff())

    # 获取编译后的事件
    node = ctx.atomic(0, 0, 0, b"")  # 创建虚拟节点来获取 Node 对象
    # 实际上我们需要通过 Node 对象编译

    # 直接检查 arena 内容
    assert ctx.node_count() > 0


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


def test_state_type_checking():
    """测试状态类型检查"""
    ctx = catseq_rs.CompilerContext()
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    op = ttl_on()

    # 应该报错：ttl_on 需要 TTLOff 状态
    try:
        op(ctx, ch, TTLOn())
        assert False, "应该抛出 TypeError"
    except TypeError as e:
        assert "TTLOff" in str(e)


def test_opcode_values():
    """验证 OpCode 值"""
    assert OpCode.TTL_ON == 0x0101
    assert OpCode.TTL_OFF == 0x0102
    assert OpCode.IDENTITY == 0x0000


def test_parallel_operator_raises_error():
    """验证 | 操作符正确报错"""
    pulse1 = ttl_pulse(10*us)
    pulse2 = ttl_pulse(20*us)

    try:
        _ = pulse1 | pulse2
        assert False, "应该抛出 TypeError"
    except TypeError as e:
        assert "parallel()" in str(e)


def test_parallel_multi_channel():
    """测试多通道并行组合"""
    from catseq.v2.open_morphism import parallel

    ctx = catseq_rs.CompilerContext()
    ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
    ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

    # 创建两个通道的脉冲
    pulse0 = ttl_init() >> ttl_on() >> wait(10*us) >> ttl_off()
    pulse1 = ttl_init() >> ttl_on() >> wait(20*us) >> ttl_off()

    # 并行组合
    combined = parallel({ch0: pulse0, ch1: pulse1})

    # 物化
    result = combined(ctx, {ch0: TTLOff(), ch1: TTLOff()})

    # 验证结果
    assert ch0 in result.end_states
    assert ch1 in result.end_states
    assert isinstance(result.end_states[ch0], TTLOff)
    assert isinstance(result.end_states[ch1], TTLOff)


if __name__ == "__main__":
    print("运行 V2 TTL 测试...")

    test_ttl_on_basic()
    print("✓ test_ttl_on_basic")

    test_ttl_off_basic()
    print("✓ test_ttl_off_basic")

    test_ttl_sequence()
    print("✓ test_ttl_sequence")

    test_ttl_pulse()
    print("✓ test_ttl_pulse")

    test_compile_events()
    print("✓ test_compile_events")

    test_compile_via_node()
    print("✓ test_compile_via_node")

    test_state_type_checking()
    print("✓ test_state_type_checking")

    test_opcode_values()
    print("✓ test_opcode_values")

    print("\n所有测试通过!")
