#!/usr/bin/env python
"""Rust 后端 vs Python 后端性能对比

展示 Rust 编译器后端的性能优势
"""

import time
from catseq.v2.rust_backend import RustMorphism
from catseq.types.common import Channel, Board, ChannelType


def benchmark_deep_chain(depth: int):
    """测试深度链式组合"""
    print(f"\n{'='*60}")
    print(f"深度链式组合测试 (深度={depth:,})")
    print(f"{'='*60}")

    ctx = RustMorphism.create_context(capacity=depth)
    channel = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    # 构建阶段
    start = time.time()
    root = RustMorphism.atomic(ctx, channel, 1, "op0")
    for i in range(1, depth):
        root = root @ RustMorphism.atomic(ctx, channel, 1, f"op{i}")
    build_time = time.time() - start

    # 编译阶段
    start = time.time()
    events = root.compile()
    compile_time = time.time() - start

    print(f"  构建时间: {build_time:.4f}s")
    print(f"  编译时间: {compile_time:.4f}s")
    print(f"  总时间:   {build_time + compile_time:.4f}s")
    print(f"  节点数:   {len(events):,}")
    print(f"  总时长:   {root.total_duration_cycles:,} 时钟周期")

    return build_time + compile_time


def benchmark_wide_parallel(width: int):
    """测试宽并行组合"""
    print(f"\n{'='*60}")
    print(f"宽并行组合测试 (通道数={width})")
    print(f"{'='*60}")

    ctx = RustMorphism.create_context(capacity=width)

    # 构建阶段
    start = time.time()
    nodes = []
    for i in range(width):
        channel = Channel(Board("RWG_0"), i, ChannelType.TTL)
        nodes.append(RustMorphism.atomic(ctx, channel, 10 * (i + 1), f"op{i}"))

    root = nodes[0]
    for node in nodes[1:]:
        root = root | node
    build_time = time.time() - start

    # 编译阶段
    start = time.time()
    events = root.compile()
    compile_time = time.time() - start

    print(f"  构建时间: {build_time:.4f}s")
    print(f"  编译时间: {compile_time:.4f}s")
    print(f"  总时间:   {build_time + compile_time:.4f}s")
    print(f"  节点数:   {len(events):,}")
    print(f"  总时长:   {root.total_duration_cycles:,} 时钟周期")

    return build_time + compile_time


def benchmark_complex_nested(size: int):
    """测试复杂嵌套组合 (A|B) @ (C|D) @ ..."""
    print(f"\n{'='*60}")
    print(f"复杂嵌套组合测试 (层数={size})")
    print(f"{'='*60}")

    ctx = RustMorphism.create_context(capacity=size * 2)

    start = time.time()
    root = None
    for i in range(size):
        ch0 = Channel(Board("RWG_0"), i * 2, ChannelType.TTL)
        ch1 = Channel(Board("RWG_0"), i * 2 + 1, ChannelType.TTL)

        n1 = RustMorphism.atomic(ctx, ch0, 100, f"op{i}_0")
        n2 = RustMorphism.atomic(ctx, ch1, 100, f"op{i}_1")
        par = n1 | n2

        if root is None:
            root = par
        else:
            root = root @ par

    build_time = time.time() - start

    start = time.time()
    events = root.compile()
    compile_time = time.time() - start

    print(f"  构建时间: {build_time:.4f}s")
    print(f"  编译时间: {compile_time:.4f}s")
    print(f"  总时间:   {build_time + compile_time:.4f}s")
    print(f"  节点数:   {len(events):,}")
    print(f"  总时长:   {root.total_duration_cycles:,} 时钟周期")

    return build_time + compile_time


def main():
    print("\n" + "=" * 60)
    print("CatSeq Rust 后端性能基准测试")
    print("=" * 60)

    # 测试 1: 深度链式组合
    print("\n\n📊 测试 1: 深度链式组合 (A @ B @ C @ ...)")
    print("  - 测试递归深度限制")
    print("  - Python 版本会在 ~1000 深度时栈溢出")

    benchmark_deep_chain(1_000)
    benchmark_deep_chain(10_000)
    benchmark_deep_chain(100_000)

    # 测试 2: 宽并行组合
    print("\n\n📊 测试 2: 宽并行组合 (A | B | C | ...)")
    print("  - 测试通道冲突检测性能")

    benchmark_wide_parallel(100)
    benchmark_wide_parallel(1_000)

    # 测试 3: 复杂嵌套
    print("\n\n📊 测试 3: 复杂嵌套 ((A|B) @ (C|D) @ ...)")
    print("  - 测试真实世界的复杂组合")

    benchmark_complex_nested(100)
    benchmark_complex_nested(1_000)
    benchmark_complex_nested(5_000)

    print("\n\n" + "=" * 60)
    print("✅ 所有基准测试完成！")
    print("=" * 60)
    print("\n预期结果：")
    print("  - 深度 100k: < 0.1s (Python 会栈溢出)")
    print("  - 宽度 1k:   < 0.01s")
    print("  - 嵌套 5k:   < 0.05s")
    print("\n关键优势：")
    print("  ✓ 无递归深度限制")
    print("  ✓ O(1) 时长和通道查询")
    print("  ✓ 内存局部性好（Arena 分配）")
    print("  ✓ 显式栈遍历（避免栈溢出）")


if __name__ == "__main__":
    main()
