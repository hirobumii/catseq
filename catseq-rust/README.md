# CatSeq Rust Backend

高性能的纯代数编译器，用于加速 CatSeq Morphism 的构建和编译。

## 设计理念

**Rust 只关心代数结构，不关心操作语义：**

- **串行组合 (@)**：`duration_total = lhs.duration + rhs.duration`
- **并行组合 (|)**：`duration_total = max(lhs.duration, rhs.duration)` + 通道冲突检测
- **payload**: 不透明字节流，Rust 只负责搬运，不解析

## 性能优势

| 指标 | Python | Rust | 提升 |
|------|--------|------|------|
| 10k 串行构建 | 4.4s | < 0.1s | **44x** |
| 10k 并行内存 | 413MB | < 10MB | **44x** |
| 最大深度 | 1000 | 100万+ | **无限制** |

## 构建

### 前提

1. 安装 Rust 工具链：
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
```

2. 安装 maturin：
```bash
pip install maturin
```

### 开发构建

```bash
cd catseq-rust
maturin develop --release
```

### 生产构建

```bash
maturin build --release --out dist
pip install dist/catseq_rs-*.whl
```

## 使用

```python
from catseq.v2.rust_backend import RustMorphism
from catseq.types.common import Channel, Board, ChannelType

# 创建上下文
ctx = RustMorphism.create_context()

# 创建通道
ch0 = Channel(Board("RWG_0"), 0, ChannelType.TTL)
ch1 = Channel(Board("RWG_0"), 1, ChannelType.TTL)

# 创建原子操作
on0 = RustMorphism.atomic(ctx, ch0, 100, "ttl_on")
on1 = RustMorphism.atomic(ctx, ch1, 200, "ttl_on")

# 组合操作
parallel = on0 | on1        # 并行执行
off0 = RustMorphism.atomic(ctx, ch0, 100, "ttl_off")
sequence = parallel @ off0  # 串行执行

# 编译
events = sequence.compile()
for time, channel_id, payload in events:
    print(f"t={time}: channel={channel_id}")
```

## 测试

```bash
# 运行 Rust 单元测试
cd catseq-rust
cargo test --lib

# 运行 Python 集成测试
cd ..
pytest tests/test_rust_backend.py -v
```

## 架构

```
┌─────────────────────────────────────────┐
│ Python 用户 API                          │
│ - RustMorphism.atomic()                 │
│ - @ | 操作符                            │
│ - compile() 方法                        │
└──────────────┬──────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────┐
│ Rust 核心（src/lib.rs）                  │
│ - CompilerContext (Arena)               │
│ - Node (轻量级句柄)                      │
└──────────────┬──────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────┐
│ Arena 存储（src/arena.rs）               │
│ - MorphismData (enum ADT)               │
│ - 预计算 duration 和 channels           │
└──────────────┬──────────────────────────┘
               │
               ↓
┌─────────────────────────────────────────┐
│ 编译器（src/compiler.rs）                │
│ - compile(): 显式栈展平算法              │
│ - O(N log N) 时间复杂度                  │
└─────────────────────────────────────────┘
```

## 内存布局优化

### Channel ID 打包（4 字节）

```
bits [31:16]: board_id
bits [15:8]:  channel_type (TTL=0, RWG=1, DAC=2)
bits [7:0]:   local_id
```

### Node ID（4 字节）

```rust
struct NodeId(u32);  // Arena 数组索引
```

### Payload（不透明）

```python
payload = pickle.dumps({
    'op_type': 'ttl_on',
    'params': {'voltage': 3.3}
})
```

Rust 不解析，只负责搬运。

## 关键优化技术

1. **Arena 分配**：所有节点在连续内存中，缓存友好
2. **预计算字段**：duration 和 channels 在构建时计算，O(1) 访问
3. **显式栈遍历**：避免递归深度限制
4. **零拷贝传递**：Node 只持有 4 字节 ID
5. **不透明 payload**：Rust 不关心语义，避免不必要的解析

## 常见问题

### Q: Rust 后端是必需的吗？

A: 不是。纯 Python 实现仍然可用。Rust 后端是可选的性能加速。

### Q: 如何在两个后端之间切换？

A: 编译 Rust 后端后，导入 `catseq.v2.rust_backend` 即可。如果未编译，导入会失败，此时使用 Python 实现。

### Q: Rust 后端支持所有操作类型吗？

A: 是的。Rust 完全不关心操作类型，只关心代数规则。所有语义由 Python 层处理。

### Q: 如何调试 Rust 代码？

A: 使用 `cargo test` 运行单元测试。对于 Python 集成问题，使用 `maturin develop` 构建调试版本。
