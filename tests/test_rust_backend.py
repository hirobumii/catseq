"""测试 Rust 后端的正确性和性能 (V2 Hybrid Architecture)

此测试直接针对 Rust 扩展模块 (catseq_rs) 及其 Python 包装器 (RustMorphism)。
验证核心的数据存储、组合逻辑 (Arena) 和编译器 (Compiler) 是否工作正常。

前提：必须先编译 Rust 后端
    cd catseq-rust && maturin develop --release
"""

import pytest

# 如果 Rust 后端未安装，跳过所有测试
pytest.importorskip("catseq_rs")

from catseq.v2.rust_backend import RustMorphism, pack_channel_id, unpack_channel_id
from catseq.types.common import Channel, Board, ChannelType
from catseq.v2.opcodes import OpCode  # <--- 关键引入：使用 V2 定义的操作码


class TestChannelPacking:
    """测试通道 ID 的打包/解包逻辑 (Bitwise Operations)"""

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
        """验证不同通道生成不同的 ID"""
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
    """测试基本的组合操作 (Atomic, Sequential, Parallel)"""

    def test_atomic_creation(self):
        """测试原子操作创建"""
        ctx = RustMorphism.create_context()
        channel = Channel(Board("RWG_0"), 0, ChannelType.TTL)

        # 修正：传递 OpCode 枚举 (int) 而非字符串
        node = RustMorphism.atomic(ctx, channel, 100, OpCode.TTL_ON, b"")

        assert node.total_duration_cycles == 100
        assert len(node.channels) == 1

    def test_sequential_composition(self):
        """测试串行组合 (@)"""
        ctx = RustMorphism.create_context()
        channel = Channel(Board("RWG_0"), 0, ChannelType.TTL)

        # 修正：传递 OpCode
        n1 = RustMorphism.atomic(ctx, channel, 100, OpCode.TTL_ON, b"")
        n2 = RustMorphism.atomic(ctx, channel, 50, OpCode.IDENTITY, b"") # wait -> IDENTITY

        seq = n1 @ n2

        assert seq.total_duration_cycles == 150
        # 验证 Rust 后端正确计算了涉及的通道
        assert len(seq.channels) == 1

    def test_parallel_composition(self):
        """测试并行组合 (|)"""
        ctx = RustMorphism.create_context()
        ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
        ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

        n1 = RustMorphism.atomic(ctx, ch0, 100, OpCode.TTL_ON, b"")
        n2 = RustMorphism.atomic(ctx, ch1, 200, OpCode.TTL_ON, b"")

        par = n1 | n2

        assert par.total_duration_cycles == 200  # max(100, 200)
        assert len(par.channels) == 2

    def test_parallel_channel_conflict(self):
        """测试并行组合的通道冲突检测"""
        ctx = RustMorphism.create_context()
        channel = Channel(Board("RWG_0"), 0, ChannelType.TTL)

        n1 = RustMorphism.atomic(ctx, channel, 100, OpCode.TTL_ON, b"")
        n2 = RustMorphism.atomic(ctx, channel, 100, OpCode.TTL_OFF, b"")

        # 应该抛出 ValueError，因为同一通道不能并行
        with pytest.raises(ValueError, match="disjoint"):
            _ = n1 | n2


class TestCompilation:
    """测试编译功能 (Graph Traversal -> Flat Events)"""

    def test_compile_atomic(self):
        """测试编译单个原子操作"""
        ctx = RustMorphism.create_context()
        channel = Channel(Board("RWG_0"), 0, ChannelType.TTL)

        node = RustMorphism.atomic(ctx, channel, 100, OpCode.TTL_ON, b"\x01")
        events = node.compile()

        assert len(events) == 1
        time, channel_id, op_code, payload = events[0]
        
        assert time == 0
        assert channel_id == pack_channel_id(channel)
        assert op_code == OpCode.TTL_ON  # 验证返回的是 int
        assert payload == b"\x01"       # 验证返回的是 bytes

    def test_compile_sequential(self):
        """测试编译串行组合"""
        ctx = RustMorphism.create_context()
        channel = Channel(Board("RWG_0"), 0, ChannelType.TTL)

        # 使用不同的 OpCode 方便区分
        n1 = RustMorphism.atomic(ctx, channel, 100, OpCode.TTL_ON, b"")
        n2 = RustMorphism.atomic(ctx, channel, 50, OpCode.TTL_OFF, b"")
        seq = n1 @ n2

        events = seq.compile()

        assert len(events) == 2
        # Event 1: t=0, TTL_ON
        assert events[0][0] == 0
        assert events[0][2] == OpCode.TTL_ON
        # Event 2: t=100, TTL_OFF
        assert events[1][0] == 100
        assert events[1][2] == OpCode.TTL_OFF

    def test_compile_parallel(self):
        """测试编译并行组合"""
        ctx = RustMorphism.create_context()
        ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
        ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

        n1 = RustMorphism.atomic(ctx, ch0, 100, OpCode.TTL_ON, b"")
        n2 = RustMorphism.atomic(ctx, ch1, 50, OpCode.TTL_OFF, b"")
        par = n1 | n2

        events = par.compile()

        assert len(events) == 2
        # 并行操作起始时间都是 0
        assert events[0][0] == 0
        assert events[1][0] == 0
        
        # 验证包含两个不同的通道
        channels = {unpack_channel_id(e[1])[2] for e in events}
        assert channels == {0, 1}


class TestComplexCompositions:
    """测试复杂的嵌套组合模式"""

    def test_nested_composition(self):
        """测试 (A | B) @ C"""
        ctx = RustMorphism.create_context()
        ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
        ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

        # A: ch0, 100ns
        a = RustMorphism.atomic(ctx, ch0, 100, OpCode.TTL_ON, b"")
        # B: ch1, 50ns
        b = RustMorphism.atomic(ctx, ch1, 50, OpCode.TTL_ON, b"")
        # C: ch0, 30ns
        c = RustMorphism.atomic(ctx, ch0, 30, OpCode.TTL_OFF, b"")

        ab = a | b      # duration = max(100, 50) = 100
        result = ab @ c # duration = 100 + 30 = 130

        assert result.total_duration_cycles == 130

        events = result.compile()
        assert len(events) == 3
        
        # 验证 C 的起始时间
        # A 和 B 都在 t=0 开始
        # C 必须在 AB 整体结束后开始，即 t=100
        # 即使 B 在 t=50 就结束了，但 parallel 块作为一个整体是 100
        c_events = [e for e in events if e[2] == OpCode.TTL_OFF]
        assert len(c_events) == 1
        assert c_events[0][0] == 100

    def test_multiple_boards(self):
        """测试多板卡编译分组"""
        ctx = RustMorphism.create_context()
        ch_board0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
        ch_board1 = Channel(Board("RWG_1"), 0, ChannelType.TTL)

        n1 = RustMorphism.atomic(ctx, ch_board0, 100, OpCode.TTL_ON, b"")
        n2 = RustMorphism.atomic(ctx, ch_board1, 100, OpCode.TTL_ON, b"")
        par = n1 | n2

        grouped = par.compile_by_board()

        assert len(grouped) == 2
        assert 0 in grouped  # board 0
        assert 1 in grouped  # board 1


class TestPerformance:
    """性能测试：验证 Rust 后端处理大规模数据的能力"""

    def test_deep_chain(self):
        """测试深度链（10,000 层串行）- 验证栈溢出安全性"""
        ctx = RustMorphism.create_context(capacity=10_000)
        channel = Channel(Board("RWG_0"), 0, ChannelType.TTL)

        root = RustMorphism.atomic(ctx, channel, 1, OpCode.TTL_ON, b"")
        
        # 连续串联 9999 次
        for _ in range(1, 10_000):
            next_op = RustMorphism.atomic(ctx, channel, 1, OpCode.TTL_ON, b"")
            root = root @ next_op

        assert root.total_duration_cycles == 10_000

        # 编译应该在毫秒级完成，且不引发 RecursionError
        events = root.compile()
        assert len(events) == 10_000
        assert events[-1][0] == 9_999  # 最后一个事件在 t=9999

    def test_wide_parallel(self):
        """测试宽并行（100 个通道）- 验证内存和排序性能"""
        ctx = RustMorphism.create_context(capacity=100)

        nodes = []
        for i in range(100):
            channel = Channel(Board("RWG_0"), i, ChannelType.TTL)
            # 使用 i 作为 OpCode 仅用于测试区分
            op_val = 0x0100 + i if i < 255 else 0x0100 # 防止 u16 溢出
            nodes.append(RustMorphism.atomic(ctx, channel, 100, int(op_val), b""))

        # 逐步并行组合
        root = nodes[0]
        for node in nodes[1:]:
            root = root | node

        assert root.total_duration_cycles == 100

        events = root.compile()
        assert len(events) == 100