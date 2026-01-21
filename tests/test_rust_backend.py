"""测试 Rust 后端的正确性和性能

前提：必须先编译 Rust 后端
    cd catseq-rust && maturin develop --release
"""

import pytest

# 如果 Rust 后端未安装，跳过所有测试
pytest.importorskip("catseq_rs")

from catseq.v2.rust_backend import RustMorphism, pack_channel_id, unpack_channel_id
from catseq.types.common import Channel, Board, ChannelType


class TestChannelPacking:
    """测试通道 ID 的打包/解包"""

    def test_pack_unpack_ttl(self):
        """测试 TTL 通道的打包和解包"""
        channel = Channel(Board("RWG_0"), 5, ChannelType.TTL)
        packed = pack_channel_id(channel)

        board_id, channel_type, local_id = unpack_channel_id(packed)
        assert board_id == 0
        assert channel_type == 0  # TTL
        assert local_id == 5

    def test_pack_unpack_rwg(self):
        """测试 RWG 通道的打包和解包"""
        channel = Channel(Board("RWG_1"), 3, ChannelType.RWG)
        packed = pack_channel_id(channel)

        board_id, channel_type, local_id = unpack_channel_id(packed)
        assert board_id == 1
        assert channel_type == 1  # RWG
        assert local_id == 3

    def test_different_channels_different_ids(self):
        """验证不同通道有不同的 ID"""
        ch1 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
        ch2 = Channel(Board("RWG_0"), 1, ChannelType.TTL)
        ch3 = Channel(Board("RWG_1"), 0, ChannelType.TTL)

        id1 = pack_channel_id(ch1)
        id2 = pack_channel_id(ch2)
        id3 = pack_channel_id(ch3)

        assert id1 != id2
        assert id1 != id3
        assert id2 != id3


class TestBasicComposition:
    """测试基本的组合操作"""

    def test_atomic_creation(self):
        """测试原子操作创建"""
        ctx = RustMorphism.create_context()
        channel = Channel(Board("RWG_0"), 0, ChannelType.TTL)

        node = RustMorphism.atomic(ctx, channel, 100, "ttl_on")

        assert node.total_duration_cycles == 100
        assert len(node.channels) == 1

    def test_sequential_composition(self):
        """测试串行组合 (@)"""
        ctx = RustMorphism.create_context()
        channel = Channel(Board("RWG_0"), 0, ChannelType.TTL)

        n1 = RustMorphism.atomic(ctx, channel, 100, "ttl_on")
        n2 = RustMorphism.atomic(ctx, channel, 50, "wait")

        seq = n1 @ n2

        assert seq.total_duration_cycles == 150

    def test_parallel_composition(self):
        """测试并行组合 (|)"""
        ctx = RustMorphism.create_context()
        ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
        ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

        n1 = RustMorphism.atomic(ctx, ch0, 100, "ttl_on")
        n2 = RustMorphism.atomic(ctx, ch1, 200, "ttl_on")

        par = n1 | n2

        assert par.total_duration_cycles == 200  # max(100, 200)
        assert len(par.channels) == 2

    def test_parallel_channel_conflict(self):
        """测试并行组合的通道冲突检测"""
        ctx = RustMorphism.create_context()
        channel = Channel(Board("RWG_0"), 0, ChannelType.TTL)

        n1 = RustMorphism.atomic(ctx, channel, 100, "ttl_on")
        n2 = RustMorphism.atomic(ctx, channel, 100, "ttl_off")

        with pytest.raises(ValueError, match="disjoint"):
            _ = n1 | n2


class TestCompilation:
    """测试编译功能"""

    def test_compile_atomic(self):
        """测试编译单个原子操作"""
        ctx = RustMorphism.create_context()
        channel = Channel(Board("RWG_0"), 0, ChannelType.TTL)

        node = RustMorphism.atomic(ctx, channel, 100, "ttl_on")
        events = node.compile()

        assert len(events) == 1
        time, channel_id, payload = events[0]
        assert time == 0
        assert channel_id == pack_channel_id(channel)

    def test_compile_sequential(self):
        """测试编译串行组合"""
        ctx = RustMorphism.create_context()
        channel = Channel(Board("RWG_0"), 0, ChannelType.TTL)

        n1 = RustMorphism.atomic(ctx, channel, 100, "op1")
        n2 = RustMorphism.atomic(ctx, channel, 50, "op2")
        seq = n1 @ n2

        events = seq.compile()

        assert len(events) == 2
        assert events[0][0] == 0  # t=0
        assert events[1][0] == 100  # t=100

    def test_compile_parallel(self):
        """测试编译并行组合"""
        ctx = RustMorphism.create_context()
        ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
        ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

        n1 = RustMorphism.atomic(ctx, ch0, 100, "op1")
        n2 = RustMorphism.atomic(ctx, ch1, 50, "op2")
        par = n1 | n2

        events = par.compile()

        assert len(events) == 2
        assert events[0][0] == 0  # 同时开始
        assert events[1][0] == 0

    def test_to_flat_events(self):
        """测试解析 payload 的编译"""
        ctx = RustMorphism.create_context()
        channel = Channel(Board("RWG_0"), 0, ChannelType.TTL)

        node = RustMorphism.atomic(ctx, channel, 100, "ttl_on", {"voltage": 3.3})
        events = node.to_flat_events()

        assert len(events) == 1
        time, ch, op_type, params = events[0]
        assert time == 0
        assert ch.board.id == "RWG_0"
        assert ch.local_id == 0
        assert op_type == "ttl_on"
        assert params["voltage"] == 3.3


class TestComplexCompositions:
    """测试复杂的组合模式"""

    def test_nested_composition(self):
        """测试 (A | B) @ C"""
        ctx = RustMorphism.create_context()
        ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
        ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

        a = RustMorphism.atomic(ctx, ch0, 100, "op_a")
        b = RustMorphism.atomic(ctx, ch1, 50, "op_b")
        c = RustMorphism.atomic(ctx, ch0, 30, "op_c")

        ab = a | b
        result = ab @ c

        assert result.total_duration_cycles == 130  # max(100,50) + 30

        events = result.compile()
        assert len(events) == 3
        assert events[0][0] == 0  # A
        assert events[1][0] == 0  # B
        assert events[2][0] == 100  # C

    def test_multiple_boards(self):
        """测试多板卡编译"""
        ctx = RustMorphism.create_context()
        ch_board0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
        ch_board1 = Channel(Board("RWG_1"), 0, ChannelType.TTL)

        n1 = RustMorphism.atomic(ctx, ch_board0, 100, "op1")
        n2 = RustMorphism.atomic(ctx, ch_board1, 100, "op2")
        par = n1 | n2

        grouped = par.compile_by_board()

        assert len(grouped) == 2
        assert 0 in grouped  # board 0
        assert 1 in grouped  # board 1


class TestPerformance:
    """性能测试（与 Python 版本对比）"""

    def test_deep_chain(self):
        """测试深度链（10,000 层）"""
        ctx = RustMorphism.create_context(capacity=10_000)
        channel = Channel(Board("RWG_0"), 0, ChannelType.TTL)

        root = RustMorphism.atomic(ctx, channel, 1, "op0")
        for i in range(1, 10_000):
            next_op = RustMorphism.atomic(ctx, channel, 1, f"op{i}")
            root = root @ next_op

        assert root.total_duration_cycles == 10_000

        # 编译应该在秒级完成
        events = root.compile()
        assert len(events) == 10_000
        assert events[-1][0] == 9_999  # 最后一个事件在 t=9999

    def test_wide_parallel(self):
        """测试宽并行（100 个通道）"""
        ctx = RustMorphism.create_context(capacity=100)

        nodes = []
        for i in range(100):
            channel = Channel(Board("RWG_0"), i, ChannelType.TTL)
            nodes.append(RustMorphism.atomic(ctx, channel, 10 * (i + 1), f"op{i}"))

        # 逐步并行组合
        root = nodes[0]
        for node in nodes[1:]:
            root = root | node

        # 时长应该是最长的那个
        assert root.total_duration_cycles == 10 * 100

        events = root.compile()
        assert len(events) == 100
