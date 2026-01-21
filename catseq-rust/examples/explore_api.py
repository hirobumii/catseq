#!/usr/bin/env python3
"""CatSeq Rust Backend API 探索脚本

用于熟悉 catseq_rs 的使用，对比 Python 和 Rust 实现的差异，
以及评估性能提升。

运行方式:
    cd catseq-rust
    source ~/catseq/.venv/bin/activate
    python examples/explore_api.py
"""

import time
from typing import Callable

import catseq_rs
from catseq.v2.rust_backend import RustMorphism, pack_channel_id
from catseq.types.common import Channel, Board, ChannelType, AtomicMorphism, OperationType
from catseq.morphism import Morphism, from_atomic
from catseq.types.ttl import TTLState

# ==============================================================================
# Part 1: 直接使用 catseq_rs 底层 API
# ==============================================================================

print("=" * 80)
print("Part 1: catseq_rs 底层 API 探索")
print("=" * 80)

# 创建编译器上下文
ctx = catseq_rs.CompilerContext()
print(f"\n创建上下文: {ctx}")

# 创建原子节点
# ctx.atomic(channel_id: int, duration: int, payload: bytes) -> Node
node1 = ctx.atomic(0, 100, b"ttl_on")
node2 = ctx.atomic(0, 50, b"wait")
node3 = ctx.atomic(1, 200, b"rwg_pulse")

print(f"\n创建原子节点:")
print(f"  node1 (ch0, 100 cycles): {node1}")
print(f"  node2 (ch0, 50 cycles):  {node2}")
print(f"  node3 (ch1, 200 cycles): {node3}")

# 串行组合 @
seq = node1 @ node2
print(f"\n串行组合 (node1 @ node2):")
print(f"  结果: {seq}")
print(f"  时长: {seq.duration} cycles")

# 并行组合 |
# 注意: 必须是不同的通道
node_ch0 = ctx.atomic(0, 100, b"op_ch0")
node_ch1 = ctx.atomic(1, 150, b"op_ch1")
par = node_ch0 | node_ch1
print(f"\n并行组合 (ch0 | ch1):")
print(f"  结果: {par}")
print(f"  时长: {par.duration} cycles (max of 100, 150)")
print(f"  通道: {par.channels}")

# 编译
events = seq.compile()
print(f"\n编译串行组合:")
for i, (time_cycles, channel_id, payload) in enumerate(events):
    print(f"  [{i}] t={time_cycles}, ch={channel_id}, payload={payload}")

# 复杂组合: (A | B) @ C
print("\n" + "-" * 40)
print("复杂组合示例: (A | B) @ C")
a = ctx.atomic(0, 100, b"A")  # ch0, 100 cycles
b = ctx.atomic(1, 50, b"B")   # ch1, 50 cycles (shorter)
c = ctx.atomic(0, 30, b"C")   # ch0, 30 cycles

ab = a | b  # 并行，时长 = max(100, 50) = 100
abc = ab @ c  # 串行，时长 = 100 + 30 = 130

print(f"  A: ch0, 100 cycles")
print(f"  B: ch1, 50 cycles")
print(f"  C: ch0, 30 cycles")
print(f"  A | B 时长: {ab.duration} cycles")
print(f"  (A | B) @ C 时长: {abc.duration} cycles")

events = abc.compile()
print(f"\n编译结果 (按时间排序):")
for i, (t, ch, payload) in enumerate(events):
    print(f"  [{i}] t={t:3d}, ch={ch}, payload={payload}")

# ==============================================================================
# Part 2: 使用 RustMorphism 包装层 (与 Python API 兼容)
# ==============================================================================

print("\n" + "=" * 80)
print("Part 2: RustMorphism 包装层 (兼容 Python API)")
print("=" * 80)

# 创建上下文
rust_ctx = RustMorphism.create_context(capacity=10000)

# 创建通道对象 (与 Python Morphism 相同的方式)
ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)
ch2 = Channel(Board("RWG_1"), 0, ChannelType.RWG)

print(f"\n通道定义:")
print(f"  ch0: {ch0.global_id} -> packed={pack_channel_id(ch0)}")
print(f"  ch1: {ch1.global_id} -> packed={pack_channel_id(ch1)}")
print(f"  ch2: {ch2.global_id} -> packed={pack_channel_id(ch2)}")

# 创建原子操作 - 使用 OperationType 枚举，而不是字符串！
m1 = RustMorphism.atomic(rust_ctx, ch0, 1, OperationType.TTL_ON)    # 1 cycle (瞬时)
m2 = RustMorphism.atomic(rust_ctx, ch0, 2500, OperationType.IDENTITY)  # 10μs 等待
m3 = RustMorphism.atomic(rust_ctx, ch0, 1, OperationType.TTL_OFF)   # 1 cycle (瞬时)

# 组合: TTL 脉冲 = ttl_on @ wait @ ttl_off (复合操作，不是原子！)
pulse = m1 @ m2 @ m3
print(f"\nTTL 脉冲 (on @ wait @ off) - 正确的复合操作:")
print(f"  时长: {pulse.total_duration_cycles} cycles = {pulse.total_duration_cycles/250:.1f}μs")
print(f"  注意: pulse 是由 3 个原子操作组合而成，不是单个 atomic!")

# 多通道并行 - 每个通道构建自己的复合脉冲
def make_ttl_pulse(ctx, channel: Channel, wait_cycles: int) -> RustMorphism:
    """构建 TTL 脉冲的工厂函数 - 正确的做法"""
    on = RustMorphism.atomic(ctx, channel, 1, OperationType.TTL_ON)
    wait = RustMorphism.atomic(ctx, channel, wait_cycles, OperationType.IDENTITY)
    off = RustMorphism.atomic(ctx, channel, 1, OperationType.TTL_OFF)
    return on @ wait @ off

pulse_ch0 = make_ttl_pulse(rust_ctx, ch0, 2500)  # 10μs 脉冲
pulse_ch1 = make_ttl_pulse(rust_ctx, ch1, 5000)  # 20μs 脉冲

parallel = pulse_ch0 | pulse_ch1
print(f"\n并行脉冲:")
print(f"  ch0: 2500 cycles")
print(f"  ch1: 5000 cycles")
print(f"  并行时长: {parallel.total_duration_cycles} cycles")
print(f"  涉及通道: {len(parallel.channels)} 个")

# 编译并解析事件
flat_events = pulse.to_flat_events()
print(f"\n编译 TTL 脉冲 (解析后):")
for t, channel, op_type, params in flat_events:
    print(f"  t={t:4d} cycles, {channel.global_id}, op={op_type.name if hasattr(op_type, 'name') else op_type}")

# ==============================================================================
# Part 3: 与 Python Morphism 对比
# ==============================================================================

print("\n" + "=" * 80)
print("Part 3: Python vs Rust 实现对比")
print("=" * 80)

print("\n--- API 差异对比 ---")
print("""
┌─────────────────┬──────────────────────────────────┬──────────────────────────────────┐
│ 功能            │ Python Morphism                  │ Rust catseq_rs                   │
├─────────────────┼──────────────────────────────────┼──────────────────────────────────┤
│ 创建上下文      │ 不需要                           │ CompilerContext()                │
│ 原子操作        │ AtomicMorphism(channel, states,  │ ctx.atomic(ch_id, duration,      │
│                 │   duration, op_type)             │   payload)                       │
│ 状态管理        │ 显式 start_state, end_state      │ 无状态，payload 中编码           │
│ 串行组合        │ @ (严格状态匹配)                 │ @ (无状态检查)                   │
│                 │ >> (自动状态推导)                │ 无等价物                         │
│ 并行组合        │ | (自动时间对齐)                 │ | (自动时间对齐)                 │
│ 通道冲突检测    │ 有                               │ 有                               │
│ 可视化          │ lanes_view(), timeline_view()    │ 无                               │
│ 编译            │ 需要额外实现                     │ node.compile()                   │
│ 增量编译        │ 无                               │ ctx.enable_incremental()         │
│ 深度限制        │ Python 递归限制                  │ 无限制 (显式栈)                  │
└─────────────────┴──────────────────────────────────┴──────────────────────────────────┘
""")

# ==============================================================================
# Part 4: 性能对比
# ==============================================================================

print("\n" + "=" * 80)
print("Part 4: 性能对比")
print("=" * 80)

def benchmark(name: str, fn: Callable, iterations: int = 1) -> float:
    """运行基准测试"""
    start = time.perf_counter()
    for _ in range(iterations):
        result = fn()
    elapsed = time.perf_counter() - start
    avg_ms = (elapsed / iterations) * 1000
    print(f"  {name}: {avg_ms:.2f}ms (avg over {iterations} runs)")
    return avg_ms

# Rust 性能测试
print("\n--- Rust 实现性能 ---")

def rust_deep_chain(depth: int = 10000):
    ctx = catseq_rs.CompilerContext.with_capacity(depth)
    root = ctx.atomic(0, 1, b"op")
    for _ in range(depth - 1):
        root = root @ ctx.atomic(0, 1, b"op")
    return root.compile()

def rust_wide_parallel(width: int = 100):
    ctx = catseq_rs.CompilerContext.with_capacity(width)
    nodes = [ctx.atomic(i, 100, f"op{i}".encode()) for i in range(width)]
    root = nodes[0]
    for node in nodes[1:]:
        root = root | node
    return root.compile()

benchmark("深度链 (10,000 节点) 构建+编译", lambda: rust_deep_chain(10000), iterations=3)
benchmark("宽并行 (100 通道) 构建+编译", lambda: rust_wide_parallel(100), iterations=10)

# Python 性能测试
print("\n--- Python 实现性能 ---")

def python_deep_chain(depth: int = 1000):
    # Python 版本深度受限，使用较小的值
    ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

    ops = []
    current_state = TTLState.OFF
    for i in range(depth):
        next_state = TTLState.ON if i % 2 == 0 else TTLState.OFF
        op = AtomicMorphism(
            channel=ch,
            start_state=current_state,
            end_state=next_state,
            duration_cycles=1,
            operation_type=OperationType.TTL_ON if next_state == TTLState.ON else OperationType.TTL_OFF
        )
        ops.append(from_atomic(op))
        current_state = next_state

    # 串行组合
    result = ops[0]
    for op in ops[1:]:
        result = result @ op
    return result

def python_wide_parallel(width: int = 100):
    morphisms = []
    for i in range(width):
        ch = Channel(Board("RWG_0"), i, ChannelType.TTL)
        op = AtomicMorphism(
            channel=ch,
            start_state=TTLState.OFF,
            end_state=TTLState.ON,
            duration_cycles=100,
            operation_type=OperationType.TTL_ON
        )
        morphisms.append(from_atomic(op))

    result = morphisms[0]
    for m in morphisms[1:]:
        result = result | m
    return result

# 注意: Python 版本使用较小的深度，因为受递归限制
benchmark("深度链 (1,000 节点) 构建", lambda: python_deep_chain(1000), iterations=3)
benchmark("宽并行 (100 通道) 构建", lambda: python_wide_parallel(100), iterations=10)

# ==============================================================================
# Part 5: 迁移指南
# ==============================================================================

print("\n" + "=" * 80)
print("Part 5: MorphismDef 迁移指南")
print("=" * 80)

print("""
要将 MorphismDef 迁移到 Rust 后端，需要考虑以下几点：

1. **状态管理差异**
   - Python: 显式管理 start_state/end_state，编译时验证状态连续性
   - Rust: 无状态概念，操作语义编码在 payload 中

   迁移策略:
   - 保留 Python 层的状态验证逻辑
   - Rust 只负责代数结构和编译

2. **推荐的混合架构**
   ┌─────────────────────────────────────────────────────────┐
   │                    用户 API 层                          │
   │  MorphismDef / 高级操作 / 状态验证                      │
   └────────────────────────┬────────────────────────────────┘
                            │
   ┌────────────────────────▼────────────────────────────────┐
   │              RustMorphism 包装层                        │
   │  Channel 打包 / Payload 编码 / 事件解析                 │
   └────────────────────────┬────────────────────────────────┘
                            │
   ┌────────────────────────▼────────────────────────────────┐
   │                catseq_rs (Rust)                         │
   │  Arena 分配 / 代数组合 / 高效编译                       │
   └─────────────────────────────────────────────────────────┘

3. **何时使用 Rust**
   - ✅ 大规模序列 (>1000 操作)
   - ✅ 深度嵌套组合
   - ✅ 需要增量编译
   - ❌ 简单的单脉冲操作 (overhead 不值得)
   - ❌ 需要丰富的可视化调试
""")

# ==============================================================================
# Part 6: 交互式探索
# ==============================================================================

print("\n" + "=" * 80)
print("Part 6: 交互式探索")
print("=" * 80)

print("""
以下对象已导入，可在交互模式下使用:

  catseq_rs         - Rust 模块
  ctx               - CompilerContext 实例
  ch0, ch1, ch2     - Channel 实例
  rust_ctx          - RustMorphism 用的上下文

如需交互式探索，运行:
  python -i examples/explore_api.py

示例:
  >>> n = ctx.atomic(0, 100, b"test")
  >>> n.duration
  100
  >>> (n @ n).compile()
  [(0, 0, b'test'), (100, 0, b'test')]
""")

if __name__ == "__main__":
    print("\n✅ 探索脚本运行完成")
