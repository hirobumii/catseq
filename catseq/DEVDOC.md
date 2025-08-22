# Cat-SEQ: 基于幺半范畴的时序控制框架开发文档

**版本**: 2.2
**日期**: 2025-08-22

## 一、 核心抽象：幺半范畴 (Monoidal Category)

Cat-SEQ 框架的理论基石是**范畴论**，具体而言是**幺半范畴**。这一选择旨在将时序编程从传统的“命令硬件如何做”的**指令式**思想，转变为“描述实验是什么”的**声明式**思想。我们通过建立物理概念到范畴论元素的精确映射，获得了一个代数结构清晰、组合能力强大的时序描述系统。

### 1.1 对象 (Object)
在 Cat-SEQ 中，一个**对象 (Object)** 代表了**整个实验系统在某一瞬时（snapshot）的完整状态**。它不是指单个硬件，而是所有相关硬件资源及其状态的集合。在实现上，这是一个由 `(通道, 具体状态)` 对组成的元组 (Tuple)。

### 1.2 态射 (Morphism)
**态射 (Morphism)** 是我们框架的原子单元，它代表了一个**持续一段时间的物理过程**。

---
### 1.3 核心模型 v2: 基于同步通道的架构 (Core Model v2: Architecture based on Synchronized Lanes)

在实践中，我们发现原始的、纯粹的复合与张量积模型虽然理论上清晰，但在处理性能和复杂的多通道同步时遇到了挑战。为了解决这些问题，核心模型演进到了一个更强大、更具体的**“同步通道” (Synchronized Lanes)** 架构。

#### 1.3.1 `PrimitiveMorphism` (原子态射)

`PrimitiveMorphism` 是新模型中最基础的构建单元。它代表一个**不可再分的、作用于单一通道的原子操作**。例如，“将TTL_0通道设为高电平”就是一个原子态射。

#### 1.3.2 `LaneMorphism` (通道态射)

`LaneMorphism` 是用户与之交互的主要接口，也是所有复合操作的结果。它的核心是一个“通道字典” (`lanes: {Channel: [PrimitiveMorphism, ...], ...}`)，其中每个“键”是一个硬件通道，每个“值”是一个在该通道上顺序执行的 `PrimitiveMorphism` 列表。

`LaneMorphism` 的一个最关键特性是**同步性**：在其内部，所有通道（lanes）的总时长都被**严格保证是相等的**。

#### 1.3.3 新的复合运算符

新的模型重新定义了 `@` (串行) 和 `|` (并行) 运算符的行为，使其变得更“智能”。

*   **`|` (并行与同步)**: `M1 | M2`
    *   **职责**: 合并两个 `LaneMorphism` 的通道，并确保所有通道的时长同步。
    *   **行为**: 它会计算所有通道的总时长，找出最长的一个 (`max_duration`)。然后，它会自动在所有较短的通道末尾**追加 `IdentityMorphism`** (单位态射，即“等待”)，直到它们的总时长也等于 `max_duration`。

*   **`@` (串行与对齐)**: `M1 @ M2`
    *   **职责**: 将 `M2` 的操作序列追加到 `M1` 对应的通道上。
    *   **行为**: 对于 `M2` 中定义的每个通道，它会将其 `PrimitiveMorphism` 列表追加到 `M1` 中相应的通道列表之后。对于 `M1` 中存在但 `M2` 中不存在的通道（即“直通”通道），它会自动在这些通道末尾追加 `IdentityMorphism`，以确保在 `M2` 执行期间，这些通道的状态被保持，并最终与执行了操作的通道**在总时长上重新对齐**。

这个新模型通过在每次并行操作时强制同步，极大地简化了时序的构建，并从根本上解决了长序列的性能问题。

---

## 二、 类型与接口设计

为了实现一个健壮且可扩展的系统，我们定义了一系列核心的基类和接口协议。

*   **`catseq/protocols.py`**: 这是整个系统的基石，定义了所有核心的抽象基类和协议，且不依赖任何其他模块，从而解决了循环依赖问题。
    *   `State`: 所有硬件状态的基类。
    *   `Channel`: 所有硬件通道标识符的基类。它通过实现 `__new__` 方法来确保每个通道名对应一个单例对象。
    *   `HardwareInterface`: 定义了所有硬件“规则”类必须遵守的接口，例如 `validate_transition` 方法。

*   **从泛型到具体基类**:
    *   在开发过程中，我们发现使用 `TypeVar` (泛型) 来代表通道类型，虽然理论上灵活，但在处理复杂的复合操作时会导致静态类型检查器难以推断正确的类型，从而产生各种类型错误。
    *   因此，我们最终决定放弃泛型，转而使用一个具体的 `Channel` 基类。这使得 `LaneMorphism` 的类型提示就是其本身，而不再需要泛型参数，极大地增强了系统的类型安全性和稳定性。

---

## 三、 状态定义 (State Definitions)

`State` 是描述硬件瞬时静态快照的不可变数据类 (`frozen=True dataclass`)。

### 1. 通用状态 (`states/common.py`)
* `Uninitialized`: 代表硬件上电后、被软件配置前的初始状态。

### 2. TTL 状态 (`states/ttl.py`)
* `TTLState(State)`, `TTLOutputOn`, `TTLOutputOff`

### 3. DAC 状态 (`states/dac.py`)
* `DACState(State)`, `DACOff`, `DACStatic(voltage: float)`

### 4. RWG 状态 (`states/rwg.py`)

(注意：此处的定义可能已过时，请以 `catseq/states/rwg.py` 文件为准)
* `WaveformParams`, `StaticWaveform`, `RWGState`, `RWGReady`, `RWGStaged`, `RWGArmed`, `RWGActive`

---

## 四、 完整项目结构

```text
catseq/
├── __init__.py
├── protocols.py         # 【已实现】定义核心协议 (State, Channel, HardwareInterface)
├── model.py             # 【已实现】核心模型 (PrimitiveMorphism, LaneMorphism)
│
├── states/              # 【已实现】状态词汇表包
│   ├── ...
│
├── hardware/            # 【已实现】物理规则库包
│   ├── base.py
│   ├── ttl.py
│   └── rwg.py
│
├── morphisms/           # 【部分实现】Morphism 工厂包
│   ├── common.py
│   └── ttl.py
│
├── sequence.py          # 【待实现】高级序列构建器 (Sequence Builder)
└── compiler.py          # 【未实现】编译器/调度器
```

### 组件职责详解 (最终版)

* `protocols.py`: **类型基石**。定义了整个项目最核心的抽象基类与接口。
* `model.py`: **代数核心**。定义了 `PrimitiveMorphism` 和 `LaneMorphism`，并实现了具有“智能同步”能力的 `@` 和 `|` 运算符。
* `states/` (包): **状态词汇表**。
* `hardware/` (包): **物理规则库**。定义具体硬件类（如 `TTLDevice`）及其物理规则。
* `morphisms/` (包): **Morphism 工厂**。提供 `Hold()`, `pulse()` 等便捷函数，用于创建 `PrimitiveMorphism` 和 `LaneMorphism`。
* `sequence.py`: **(待实现)** **高级 API**。未来可以提供一个 `Sequence` 类，进一步简化时序构建。
* `compiler.py`: **(未实现)** **编译器**。接收 `LaneMorphism` 对象，并将其翻译成目标平台的指令。
