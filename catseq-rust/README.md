# CatSeq Rust Backend

**[Mandatory Core Component]**

高性能的纯代数编译器，用于加速 CatSeq Morphism 的构建、编译以及程序控制流管理。这是 CatSeq V2 架构的基础设施，负责所有核心数据结构和算法。

## 设计理念

**Rust 只关心代数结构，不关心操作语义：**

- **Morphism 层**：处理微秒级脉冲序列的代数组合
    - **串行组合 (@)**：`duration_total = lhs.duration + rhs.duration`
    - **并行组合 (|)**：`duration_total = max(lhs.duration, rhs.duration)` + 通道冲突检测
- **Program 层**：处理控制流 AST
    - **变量与表达式**：SSA 风格的变量绑定
    - **控制结构**：Loop, Match, Branch

## 性能优势

Rust 后端通过 Arena 内存布局和显式栈算法，解决了 Python 在大规模序列构建时的递归溢出和内存碎片问题。

| 指标 | Python (Legacy) | Rust (V2) | 提升 |
|------|----------------|-----------|------|
| 10k 串行构建 | 4.4s | < 0.1s | **44x** |
| 10k 并行内存 | 413MB | < 10MB | **44x** |
| 最大深度 | ~1000 (RecursionLimit) | 100万+ | **无限制** |

## 构建

### 前提

1. 安装 Rust 工具链：
```bash
curl --proto '=https' --tlsv1.2 -sSf [https://sh.rustup.rs](https://sh.rustup.rs) | sh
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

CatSeq V2 的 Python 层会自动调用此后端，用户通常不需要直接操作 `catseq_rs`，但可以通过以下方式直接访问底层 API：

```python
from catseq.v2.rust_backend import RustMorphism
from catseq.types.common import Channel, Board, ChannelType

# V2 Context 自动管理 Rust 生命周期
# ... 上层 DSL 代码 ...
```

## 测试

```bash
# 运行 Rust 单元测试 (Core Logic)
cd catseq-rust
cargo test --lib

# 运行 Python 集成测试 (Binding Layer)
cd ..
pytest tests/test_rust_backend.py -v
```

## 架构

CatSeq V2 采用双 Arena 设计，所有数据驻留于 Rust 堆中，Python 仅持有 `u32` 句柄。

```
┌─────────────────────────────────────────┐
│ Python 用户 API (catseq.v2)              │
│ - 轻量级 Handle (NodeId, ValueId)        │
│ - 业务逻辑与类型检查                      │
└──────────────┬──────────────────────────┘
               │ (u32 Handle)
               ↓
┌─────────────────────────────────────────┐
│ Rust 核心 (catseq-rust extension)        │
├──────────────────────┬──────────────────┤
│ Morphism Arena       │ Program Arena    │
│ (src/arena.rs)       │ (src/program/*)  │
│ - Atomic / Seq / Par │ - Loop / Branch  │
│ - Duration 预计算     │ - Variables      │
│ - Channel 冲突检测    │ - AST Storage    │
└──────────────┬───────┴──────────────────┘
               │
               ↓
┌─────────────────────────────────────────┐
│ 编译器 (src/compiler.rs)                 │
│ - 增量编译 (Incremental Compilation)     │
│ - Block Copy 优化                        │
│ - 显式栈展平算法 (无递归限制)              │
└─────────────────────────────────────────┘
```

## 内存布局优化

### Channel ID 打包（4 字节）

```
bits: board_id
bits [15:8]:  channel_type (TTL=0, RWG=1, DAC=2)
bits [7:0]:   local_id
```

### Handle ID（4 字节）

- **NodeId**: `u32` 索引，指向 Arena 中的操作节点
- **ValueId**: `u32` 索引，指向 Arena 中的变量或常量

### Payload（零拷贝）

具体波形数据（Payload）作为不透明字节流 (`Arc<Vec<u8>>`) 在 Rust 内部传递，完全避免了 Python <-> Rust 边界的序列化开销。

## 常见问题 (FAQ)

### Q: Rust 后端是必需的吗？

A: **是的 (Mandatory)。** 在 CatSeq V2 中，Rust 后端不再是可选的优化组件，而是系统的核心。它负责所有的内存管理、代数规则校验和最终的编译生成。如果没有 Rust 后端，CatSeq V2 将无法运行。

### Q: 为什么必须使用 Rust？

A: Python 的对象开销（每个对象 48+ 字节）和递归深度限制使得处理复杂的量子控制序列（通常包含数万到数百万个操作）变得不可行。Rust 实现的 Arena 架构将每个操作压缩为紧凑的枚举（Enum），并将指针开销降至 4 字节整数，同时实现了 O(N) 的线性编译算法。

### Q: 如何调试 Rust 代码？

A: 使用 `cargo test` 运行单元测试。Rust 侧有完整的测试套件覆盖了代数逻辑和编译算法。对于 Python 集成问题，可以使用 `maturin develop` 构建调试版本。