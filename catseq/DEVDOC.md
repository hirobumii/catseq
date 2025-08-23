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
### 1.4 核心模型 v3: 函数式API与延迟执行 (Core Model v3: Functional API and Deferred Execution)

在v2模型的基础上，为了提升API的表达能力和易用性，我们引入了函数式的“延迟执行”模式。这个设计的核心思想是**将时序的“定义”与“执行”分离**。

#### 1.4.1 `MorphismBuilder` (态射构建器)

这个新模式的核心是 `catseq/builder.py` 中定义的 `MorphismBuilder` 类。它扮演一个“态射配方”或“构建器”的角色。

*   **它是什么**: 当你调用一个新的工厂函数，如 `ttl.pulse(duration=10e-6)` 时，它不再立即返回一个具体的 `LaneMorphism`。相反，它返回一个 `MorphismBuilder` 对象。这个对象内部封装了一个“生成器”函数，这个函数知道如何根据一个给定的 `(channel, from_state)` 来创建最终的态射。
*   **它不是什么**: 它本身不是一个态射。它没有 `dom`，`cod` 或 `duration`。它仅仅是一个待执行的计划。

#### 1.4.2 新的复合与执行风格

`MorphismBuilder` 类重载了 `@` 运算符，使其可以**在执行前进行复合**。

*   **`@` (复合构建器)**: `builder1 @ builder2` 会将两个构建器的生成器函数链接起来，创建一个新的、更长的 `MorphismBuilder`。
*   **`()` (执行)**: `MorphismBuilder` 是一个可调用对象 (callable)。当你最终拥有了完整的序列配方后，你可以通过调用它并传入一个 `channel` 对象来执行它，从而生成一个具体的、可执行的 `LaneMorphism`。

**示例:**
```python
# 1. 从工厂函数创建构建器 (此时没有创建任何具体的态射)
from catseq.morphisms import ttl
from catseq.morphisms.common import hold

pulse_def = ttl.pulse(10e-6)
hold_def = hold(5e-3)

# 2. 复合构建器来定义序列的“形状”
sequence_def = pulse_def @ hold_def @ pulse_def

# 3. 在最后一刻，将定义好的“形状”应用到一个具体的通道上
#    这会触发执行，并返回一个v2模型中的 LaneMorphism
ttl_channel = Channel("TTL_0", TTLDevice)
final_sequence = sequence_def(ttl_channel)
```

#### 1.4.3 设计思路与权衡 (Design Rationale & Trade-offs)

*   **为什么需要一个新类**: 我们曾考虑使用标准的 `functools.partial`，但它不允许我们重载 `@` 运算符。为了实现构建器之间的复合，我们必须拥有自己的类 (`MorphismBuilder`)。
*   **便利性与安全性**: 在 `ttl.py` 的工厂函数（如 `turn_on`）中，我们为 `from_state` 提供了默认值（例如，`turn_on` 默认来自 `TTLOutputOff`）。这大大提升了编写简单序列时的便利性。但它也带来了一个风险：如果开发者在不恰当的上下文中使用它（例如，在一个已经是 `On` 的状态后调用 `turn_on()`），它会在执行时（而不是定义时）因违反逻辑而失败。这是一个在“便利性”和“绝对的显式安全”之间的权衡，我们选择了前者以优化用户体验。
*   **通用 `hold`**: 这个新模式使得 `morphisms.common.hold` 变得更加通用。因为它是一个延迟执行的配方，所以一个单独的 `hold(duration)` 可以在任何通道（TTL, RWG等）上使用，在执行时它会自动适应前一个状态。这解决了为不同硬件创建不同 `hold` 函数的命名冲突问题。

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

### 4. RWG 状态 (`states/rwg.py`) — 架构演进

RWG 的状态模型是理解本框架抽象层次的关键。我们区分了**用户感知的“纯净”状态**和**硬件内部的“物理”状态**。

*   **用户感知的状态 (User-Facing State)**: 对于时序编写者而言，RWG 通道只有两种状态：`RF_Off` (一个抽象概念) 和 `RWGActive`。`RWGActive` 是一个富状态，它包含了当前时刻精确的频率、幅度和相位信息。用户编写的序列，例如 `ramp1 @ ramp2`，是 `RWGActive` 状态之间的一个平滑过渡。
*   **内部物理状态 (Internal Physical States)**: `RWGReady`, `RWGStaged`, `RWGArmed` 这些状态真实存在于硬件的生命周期中，但它们是**对用户隐藏的实现细节**。用户不应该也无须为这些中间状态手动创建态射。

这个设计的核心思想是，用户只需声明**期望的物理输出（波形）**，而将如何实现这一输出的复杂底层操作（参数写入、准备、使能）交给**编译器**去自动编排。

---

## 四、 完整项目结构

```text
catseq/
├── __init__.py
├── protocols.py         # 【已实现】定义核心协议 (State, Channel, HardwareInterface)
├── model.py             # 【已实现】核心模型 (PrimitiveMorphism, LaneMorphism)
├── builder.py           # 【已实现】定义 MorphismBuilder，用于延迟执行
│
├── states/              # 【已实现】状态词汇表包
│   ├── ...
│
├── hardware/            # 【已实现】物理规则库包
│   ├── base.py
│   ├── ttl.py
│   └── rwg.py
│
├── morphisms/           # 【已实现】Morphism 工厂包 (返回 MorphismBuilder)
│   ├── common.py
│   └── ttl.py
│
├── sequence.py          # 【待实现】高级序列构建器 (如 repeat 函数)
└── compiler.py          # 【未实现】编译器/调度器
```

### 组件职责详解 (最终版)

* `protocols.py`: **类型基石**。定义了整个项目最核心的抽象基类与接口。
* `model.py`: **代数核心 (执行层)**。定义了 `PrimitiveMorphism` 和 `LaneMorphism`，并实现了具有“智能同步”能力的 `@` 和 `|` 运算符。这些是具体的、可执行的态射。
* `builder.py`: **函数式API (定义层)**。定义了 `MorphismBuilder` 类，它使得时序的“定义”与“执行”可以被分离。
* `states/` (包): **状态词汇表**。
* `hardware/` (包): **物理规则库**。定义具体硬件类（如 `TTLDevice`）及其物理规则。
* `morphisms/` (包): **Morphism 工厂**。提供 `hold()`, `pulse()` 等便捷函数，用于创建 `MorphismBuilder` 对象。
* `sequence.py`: **(待实现)** **高级 API**。未来可以提供一个 `Sequence` 类或 `repeat()` 这样的高阶函数，进一步简化时序构建。
* `compiler.py`: **(未实现)** **编译器**。接收用户定义的“纯净” `LaneMorphism` 对象，并将其编排、优化和翻译成目标平台的最终指令。该组件的**关键职责**包括：
    *   **序列展开 (Sequence Expansion)**: 将用户定义的高阶态射（如一个 `ramp`）展开成其底层的、硬件必需的低阶态射序列（如 `stage_waveform @ arm_and_rf_on @ active_ramp`）。
    *   **调度与交错 (Scheduling and Interleaving)**: 智能地重新排序指令以优化硬件使用。最关键的例子是，编译器会自动将下一个波形 (`ramp2`) 的参数写入 (`stage_waveform`) 操作，调度到当前波形 (`ramp1`) 正在输出的时间段内并行执行。
    *   **时长计算与修正 (Duration Calculation and Patching)**: 对类似 `stage_waveform` 这样需要与硬件通信的态射，编译器需要计算其真实的执行时间，并更新 `LaneMorphism` 对象中的占位时长。
    *   **时序约束验证 (Timing Constraint Validation)**: 在调度完成后，编译器必须验证复杂的硬件时序约束。例如，它需要确保 `ramp1` 的时长足够长，以隐藏 `ramp2` 的参数写入时间。如果时间不足，编译器应报错，并向用户提供清晰的反馈。