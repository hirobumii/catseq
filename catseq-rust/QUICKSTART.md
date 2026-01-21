# 快速开始：CatSeq Rust 后端

## 5 分钟上手指南

### 1. 一键构建

```bash
cd catseq-rust
chmod +x build.sh
./build.sh
```

这个脚本会：
- ✅ 检查 Rust 和 maturin 是否安装
- ✅ 运行 Rust 单元测试
- ✅ 构建 Python 扩展
- ✅ 运行 Python 集成测试

### 2. 第一个程序

```python
from catseq.v2.rust_backend import RustMorphism
from catseq.types.common import Channel, Board, ChannelType
from catseq.time_utils import us

# 创建编译器上下文
ctx = RustMorphism.create_context()

# 定义通道
ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

# 创建 TTL 脉冲：ON -> wait(40μs) -> OFF
pulse = (
    RustMorphism.atomic(ctx, ch0, 1, "ttl_on") @
    RustMorphism.atomic(ctx, ch0, 10_000, "wait") @  # 40μs = 10000 cycles @ 250MHz
    RustMorphism.atomic(ctx, ch0, 1, "ttl_off")
)

# 两个通道并行执行
pulse1 = RustMorphism.atomic(ctx, ch0, 1000, "pulse")
pulse2 = RustMorphism.atomic(ctx, ch1, 2000, "pulse")
parallel = pulse1 | pulse2

print(f"总时长: {parallel.total_duration_cycles} 时钟周期")
print(f"涉及通道: {len(parallel.channels)}")

# 编译并查看事件
events = parallel.to_flat_events()
for time, channel, op_type, params in events:
    print(f"t={time}: {channel} -> {op_type}")
```

### 3. 性能基准测试

```python
import time

# 构建深度 10,000 的链
ctx = RustMorphism.create_context(capacity=10_000)
ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

start = time.time()
root = RustMorphism.atomic(ctx, ch, 1, "op0")
for i in range(1, 10_000):
    root = root @ RustMorphism.atomic(ctx, ch, 1, f"op{i}")
build_time = time.time() - start

start = time.time()
events = root.compile()
compile_time = time.time() - start

print(f"构建时间: {build_time:.4f}s")
print(f"编译时间: {compile_time:.4f}s")
print(f"总时长: {root.total_duration_cycles} 周期")
```

**预期输出**（Rust vs Python）：
```
Rust:   构建 0.002s, 编译 0.001s
Python: 构建 4.400s, 编译 0.100s
提升:   2200x,      100x
```

### 4. 与现有代码集成

Rust 后端的 API 设计为兼容现有 catseq API。如果您有现有的 TTL 操作封装：

```python
from catseq.v2.rust_backend import RustMorphism, get_or_create_global_context
from catseq.types.common import Channel
from catseq.time_utils import time_to_cycles

# 全局上下文（可选，用于快速原型）
_ctx = get_or_create_global_context()

def ttl_on_rust(channel: Channel) -> RustMorphism:
    """使用 Rust 后端的 TTL ON 操作"""
    return RustMorphism.atomic(_ctx, channel, 1, "ttl_on")

def wait_rust(channel: Channel, duration_seconds: float) -> RustMorphism:
    """使用 Rust 后端的 WAIT 操作"""
    cycles = time_to_cycles(duration_seconds)
    return RustMorphism.atomic(_ctx, channel, cycles, "wait")

# 使用与之前完全相同
from catseq.time_utils import us
pulse = ttl_on_rust(ch) @ wait_rust(ch, 40*us) @ ttl_off_rust(ch)
```

### 5. 调试技巧

**查看节点信息**：
```python
print(node)  # <Node id=42 duration=1000 channels=2>
print(f"叶子数: {node.leaf_count()}")
print(f"深度: {node.max_depth()}")
```

**查看编译后的事件**：
```python
events = node.compile()
for time, channel_id, payload in events[:10]:  # 只看前 10 个
    print(f"t={time:>6}: ch={channel_id:#010x}")
```

**按板卡分组**：
```python
grouped = node.compile_by_board()
for board_id, board_events in grouped.items():
    print(f"Board {board_id}: {len(board_events)} events")
```

### 6. 常见陷阱

**❌ 错误：通道冲突**
```python
n1 = RustMorphism.atomic(ctx, ch0, 100, "op1")
n2 = RustMorphism.atomic(ctx, ch0, 100, "op2")
result = n1 | n2  # ValueError: Parallel composition requires disjoint channels
```

**✅ 正确：使用不同通道**
```python
result = n1 | n3  # n3 使用不同通道
```

**❌ 错误：忘记传递上下文**
```python
n1 = RustMorphism.atomic(ctx1, ch, 100, "op")
n2 = RustMorphism.atomic(ctx2, ch, 100, "op")
result = n1 @ n2  # 可能工作，但不推荐（不同 Arena）
```

**✅ 正确：共享上下文**
```python
# 所有操作使用同一个 ctx
n1 = RustMorphism.atomic(ctx, ch, 100, "op1")
n2 = RustMorphism.atomic(ctx, ch, 100, "op2")
result = n1 @ n2  # ✅
```

### 7. 进阶：自定义操作

Rust 不关心操作的具体含义，您可以自由定义：

```python
def custom_op(ctx, channel, duration, **kwargs):
    """自定义操作：任意参数都可以"""
    return RustMorphism.atomic(
        ctx, channel, duration,
        op_type="custom",
        params=kwargs  # 任意字典
    )

# 使用
op = custom_op(ctx, ch, 1000, freq=100e6, amp=0.5, phase=0.0)
```

Rust 会将 `params` 序列化为 payload，编译后原样返回。

### 8. 下一步

- 阅读 [README.md](README.md) 了解架构设计
- 查看 [tests/test_rust_backend.py](../tests/test_rust_backend.py) 学习更多用法
- 探索 [src/](src/) 了解 Rust 实现细节
