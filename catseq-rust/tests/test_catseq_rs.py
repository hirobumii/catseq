"""catseq_rs 模块的独立测试

直接测试 Rust pyo3 扩展，不依赖父项目的 Python 代码。
运行方式：
    cd catseq-rust
    ./test.sh          # 构建并测试
    pytest tests/ -v   # 仅测试（需先构建）
"""

import pytest

# 尝试导入，如果未构建则跳过
catseq_rs = pytest.importorskip("catseq_rs")


class TestCompilerContext:
    """测试 CompilerContext 类"""

    def test_create_context(self):
        """测试创建上下文"""
        ctx = catseq_rs.CompilerContext()
        assert ctx is not None
        assert ctx.node_count() == 0

    def test_create_with_capacity(self):
        """测试预分配容量创建"""
        ctx = catseq_rs.CompilerContext.with_capacity(1000)
        assert ctx.node_count() == 0

    def test_repr(self):
        """测试字符串表示"""
        ctx = catseq_rs.CompilerContext()
        assert "CompilerContext" in repr(ctx)
        assert "nodes=0" in repr(ctx)


class TestNode:
    """测试 Node 类"""

    def test_atomic_creation(self):
        """测试创建原子节点"""
        ctx = catseq_rs.CompilerContext()
        # atomic(channel_id, duration, opcode, data)
        node = ctx.atomic(0, 100, 0, b"test_payload")

        assert node is not None
        assert node.duration == 100
        assert ctx.node_count() == 1

    def test_sequential_composition(self):
        """测试串行组合 (@)"""
        ctx = catseq_rs.CompilerContext()
        n1 = ctx.atomic(0, 100, 0, b"op1")
        n2 = ctx.atomic(0, 50, 0, b"op2")

        seq = n1 @ n2

        assert seq.duration == 150
        assert ctx.node_count() == 3  # n1, n2, seq

    def test_parallel_composition(self):
        """测试并行组合 (|)"""
        ctx = catseq_rs.CompilerContext()
        n1 = ctx.atomic(0, 100, 0, b"op1")  # channel 0
        n2 = ctx.atomic(1, 200, 0, b"op2")  # channel 1

        par = n1 | n2

        assert par.duration == 200  # max(100, 200)
        assert ctx.node_count() == 3

    def test_parallel_channel_conflict(self):
        """测试并行组合的通道冲突"""
        ctx = catseq_rs.CompilerContext()
        n1 = ctx.atomic(0, 100, 0, b"op1")  # channel 0
        n2 = ctx.atomic(0, 50, 0, b"op2")   # channel 0 (conflict!)

        with pytest.raises(ValueError, match="disjoint|conflict|intersect"):
            _ = n1 | n2

    def test_node_repr(self):
        """测试节点字符串表示"""
        ctx = catseq_rs.CompilerContext()
        node = ctx.atomic(0, 100, 0, b"test")
        assert "Node" in repr(node) or "duration" in repr(node).lower()


class TestCompilation:
    """测试编译功能"""

    def test_compile_atomic(self):
        """测试编译单个原子操作"""
        ctx = catseq_rs.CompilerContext()
        node = ctx.atomic(0, 100, 42, b"payload")

        events = node.compile()

        assert len(events) == 1
        time, channel_id, opcode, data = events[0]
        assert time == 0
        assert channel_id == 0
        assert opcode == 42
        assert data == b"payload"

    def test_compile_sequential(self):
        """测试编译串行组合"""
        ctx = catseq_rs.CompilerContext()
        n1 = ctx.atomic(0, 100, 1, b"first")
        n2 = ctx.atomic(0, 50, 2, b"second")
        seq = n1 @ n2

        events = seq.compile()

        assert len(events) == 2
        assert events[0][0] == 0    # 第一个事件 t=0
        assert events[1][0] == 100  # 第二个事件 t=100

    def test_compile_parallel(self):
        """测试编译并行组合"""
        ctx = catseq_rs.CompilerContext()
        n1 = ctx.atomic(0, 100, 0, b"ch0")
        n2 = ctx.atomic(1, 50, 0, b"ch1")
        par = n1 | n2

        events = par.compile()

        assert len(events) == 2
        # 并行操作同时开始
        assert events[0][0] == 0
        assert events[1][0] == 0

    def test_compile_complex(self):
        """测试编译 (A | B) @ C"""
        ctx = catseq_rs.CompilerContext()
        a = ctx.atomic(0, 100, 0, b"A")
        b = ctx.atomic(1, 50, 0, b"B")
        c = ctx.atomic(0, 30, 0, b"C")

        ab = a | b
        result = ab @ c

        events = result.compile()

        assert len(events) == 3
        # A 和 B 在 t=0
        assert events[0][0] == 0
        assert events[1][0] == 0
        # C 在 t=100 (max(100, 50))
        assert events[2][0] == 100

    def test_compile_by_board(self):
        """测试按板卡分组编译"""
        ctx = catseq_rs.CompilerContext()
        # channel_id 高位是 board_id
        # board 0: channel 0-255
        # board 1: channel 256-511 (假设 board_id 在高位)
        n1 = ctx.atomic(0, 100, 0, b"board0")
        n2 = ctx.atomic(1, 100, 0, b"board0_ch1")
        par = n1 | n2

        # 检查是否有 compile_by_board 方法
        if hasattr(par, 'compile_by_board'):
            grouped = par.compile_by_board()
            assert isinstance(grouped, dict)


class TestIncrementalCompilation:
    """测试增量编译功能"""

    def test_enable_incremental(self):
        """测试启用增量编译"""
        ctx = catseq_rs.CompilerContext()
        ctx.enable_incremental()
        # 不应该抛出异常

    def test_incremental_compilation(self):
        """测试增量编译的正确性"""
        ctx = catseq_rs.CompilerContext()
        ctx.enable_incremental()

        n1 = ctx.atomic(0, 100, 0, b"op1")
        n2 = ctx.atomic(0, 50, 0, b"op2")

        # 第一次编译
        events1 = n1.compile()

        # 组合后再编译
        seq = n1 @ n2
        events2 = seq.compile()

        assert len(events1) == 1
        assert len(events2) == 2


class TestPerformance:
    """性能测试"""

    def test_deep_chain(self):
        """测试深度链（1000 层）"""
        ctx = catseq_rs.CompilerContext.with_capacity(1000)

        root = ctx.atomic(0, 1, 0, b"op0")
        for i in range(1, 1000):
            next_op = ctx.atomic(0, 1, 0, b"op")
            root = root @ next_op

        assert root.duration == 1000

        events = root.compile()
        assert len(events) == 1000

    def test_wide_parallel(self):
        """测试宽并行（50 个通道）"""
        ctx = catseq_rs.CompilerContext.with_capacity(50)

        nodes = []
        for i in range(50):
            nodes.append(ctx.atomic(i, 10 * (i + 1), 0, f"op{i}".encode()))

        root = nodes[0]
        for node in nodes[1:]:
            root = root | node

        assert root.duration == 10 * 50

        events = root.compile()
        assert len(events) == 50


class TestEdgeCases:
    """边界情况测试"""

    def test_empty_payload(self):
        """测试空 payload"""
        ctx = catseq_rs.CompilerContext()
        node = ctx.atomic(0, 100, 0, b"")
        events = node.compile()
        assert events[0][3] == b""  # data is 4th element

    def test_large_payload(self):
        """测试大 payload"""
        ctx = catseq_rs.CompilerContext()
        large_payload = b"x" * 10000
        node = ctx.atomic(0, 100, 0, large_payload)
        events = node.compile()
        assert events[0][3] == large_payload  # data is 4th element

    def test_zero_duration(self):
        """测试零时长"""
        ctx = catseq_rs.CompilerContext()
        node = ctx.atomic(0, 0, 0, b"instant")
        assert node.duration == 0

    def test_clear_arena(self):
        """测试清空 Arena"""
        ctx = catseq_rs.CompilerContext()
        ctx.atomic(0, 100, 0, b"test")
        assert ctx.node_count() == 1

        ctx.clear()
        assert ctx.node_count() == 0
