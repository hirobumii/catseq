# Cat-SEQ: 基于幺半范畴的时序控制框架开发文档

**版本**: 2.1
**日期**: 2025-08-21

## 一、 核心抽象：幺半范畴 (Monoidal Category)

Cat-SEQ 框架的理论基石是**范畴论**，具体而言是**幺半范畴**。这一选择旨在将时序编程从传统的“命令硬件如何做”的**指令式**思想，转变为“描述实验是什么”的**声明式**思想。我们通过建立物理概念到范畴论元素的精确映射，获得了一个代数结构清晰、组合能力强大的时序描述系统。

### 1. 对象 (Object)
在 Cat-SEQ 中，一个**对象 (Object)** 代表了**整个实验系统在某一瞬时（snapshot）的完整状态**。它不是指单个硬件，而是所有相关硬件资源及其状态的集合。

在实现上，这是一个由 `(硬件资源, 具体状态)` 对组成的元组 (Tuple)，例如：
`((Channel.RWG_RF0, RWGActive(...)), (Channel.TTL_0, TTLOutputOn()), ...)`

### 2. 态射 (Morphism)
**态射 (Morphism)** 是我们框架的原子单元，它代表了一个**持续一段时间的物理过程**。任何时序片段，无论是一个简单的等待，还是一个复杂的波形播放，都被统一抽象为态射。

一个态射 `f` 是一个从**域对象 (domain)** 到**靶对象 (codomain)** 的映射，记作 `f: dom -> cod`。它具有以下核心属性：
* `dom`: 过程开始前的系统状态 (一个**对象**)。
* `cod`: 过程结束时的系统状态 (一个**对象**)。
* `duration`: 过程的持续时间（秒）。
* `dynamics`: 描述过程如何演化的参数。例如，对于 RWG 通道，它持有 `WaveformParams` 或 `StaticWaveform` 对象。

### 3. 复合 (Composition)
**复合 (Composition)** 对应**时序的顺序执行**。给定两个态射 `f: A -> B` 和 `g: B -> C`，它们的复合 `f @ g` 形成了一个新的态射 `h: A -> C`。复合的先决条件是前一个态射的 `codomain` 必须与后一个态射的 `domain` 完全匹配。

### 4. 张量积 (Tensor Product)
**张量积 (Tensor Product)** 对应**时序的并行执行**。给定两个作用在**不相交**硬件资源上的态射 `f: A -> B` 和 `g: C -> D`，它们的张量积 `f | g` 形成了一个新的态射 `h: (A ⊗ C) -> (B ⊗ D)`。其 `duration` 取两者中的最大值。

---

## 二、 类型系统：安全与灵活的基石

为了将上述抽象模型安全、可靠地在 Python 中实现，我们严重依赖其强大的类型系统 (`typing`)。

* **`Generic[ChannelT]`**: `Morphism` 类被定义为泛型，使其能够与任意类型的硬件资源协同工作，保证了核心模型的通用性。

* **`TypeVar` 与 `bound`**: 我们通过 `ChannelT = TypeVar('ChannelT', bound=ResourceIdentifier)` 声明了类型变量 `ChannelT`。这里的 `bound` 是一个强制契约，它要求任何用于 `Morphism` 的具体硬件资源类型，都必须遵循 `ResourceIdentifier` 协议。

* **`Protocol`**: 我们使用协议（`ResourceIdentifier`, `HardwareInterface`）来定义硬件必须遵守的接口契约，而不是依赖具体的类继承。这使得 `model.py` 能够完全独立，无需导入任何具体的硬件实现，达到了最大程度的解耦。

* **`typing.Self`**: 在 `BaseHardware` 等类中，我们使用 `Self` 来注解返回自身实例的方法，这是 Python 3.11+ 的最佳实践。

---

## 三、 状态定义 (State Definitions)

`State` 是描述硬件瞬时静态快照的不可变数据类 (`frozen=True dataclass`)。

### 1. 通用状态 (`states/common.py`)
* `Uninitialized`: 代表硬件上电后、被软件配置前的初始状态。

### 2. TTL 状态 (`states/ttl.py`)
* `TTLState(State)`, `TTLInput`, `TTLOutputOn`, `TTLOutputOff`

### 3. DAC 状态 (`states/dac.py`)
* `DACState(State)`, `DACOff`, `DACStatic(voltage: float)`

### 4. RWG 状态 (`states/rwg.py`)

#### 4.1 设计演进：状态与过程的分离
我们最终的设计严格区分了**“过程描述”**和**“状态快照”**。`State` 对象本身只代表纯粹的静态快照或 FSM 标记，而描述一个过程（无论是静态保持还是动态斜坡）的参数则由 `Morphism` 的 `dynamics` 字段持有。

#### 4.2 最终数据结构定义

* **过程描述对象 (Process Descriptions)**: **由 `Morphism` 的 `dynamics` 字段持有**。
    * `WaveformParams`: 描述一个**动态**波形过程（如斜坡）。
    * `StaticWaveform`: 描述一个**静态**波形过程（如保持恒定频率）。

* **状态机 (State Machine)**:
    * `RWGState(State)`: RWG 状态的基类。
    * `RWGReady(RWGState)`: 通道已初始化，载波已设定。持有 `carrier_freq`。
    * `RWGStaged(RWGState)`: **(无波形数据)** 流程标记，表示参数已暂存。只持有 `carrier_freq`。
    * `RWGArmed(RWGState)`: **(仅限静态)** 表示一个**静态**波形的参数已生效，但 RF 输出关闭。持有 `Tuple[StaticWaveform, ...]`。
    * `RWGActive(RWGState)`: RF 信号正在有效输出。持有 `Tuple[StaticWaveform, ...]` 作为物理快照。

---

## 四、 验证模型与状态机

#### 4.1 设计演进：分层验证模型
我们最终确立了一套职责清晰的**分层验证模型**，取代了最初将所有验证逻辑都放在组合 (`@`) 时刻的方案。

1.  **创建时 (由 `morphisms` 包的工厂函数负责)**:
    * **职责**: 保证每一个被创建的 `Morphism` 都是**自洽且合法**的。
    * **检查**: 调用 `hardware` 层的方法，验证**过程参数** (`validate_dynamics`) 和 **FSM 流程** (`validate_transition`)。

2.  **组合时 (由 `@` 操作符负责)**:
    * **职责**: 保证 `Morphism` 之间的**连接**是合法的。
    * **检查**: 纯粹的数学拼接 (`f.cod == g.dom`)，以及对 `Active -> Active` 连接点的**连续性**策略检查 (`validate_continuity`)。

3.  **编译时 (由 `compiler.py` 负责)**:
    * **职责**: 执行需要完整上下文的**全局检查**。
    * **检查**: 例如，`enforce_continuity` 策略下的相位重置检查。

#### 4.2 RWG 状态机
`morphisms` 包的工厂函数在创建 `Morphism` 时，必须遵守以下由 `hardware.rwg.RWGDevice` 定义的合法转换路径。

| 流程类型 | 起始状态 (From) | 目标状态 (To) | 备注/约束 |
| :--- | :--- | :--- | :--- |
| 初始化 | `Uninitialized` | `RWGReady` | 唯一的初始化路径。 |
| **静态** | `RWGReady` | `RWGStaged` | 暂存一个静态波形。 |
| **静态** | `RWGStaged` | `RWGArmed` | 让暂存的静态波形生效。 |
| **静态** | `RWGArmed` | `RWGActive` | 打开 RF 输出。 |
| **动态** | `RWGReady` | `RWGStaged` | 暂存一个动态波形。 |
| **动态** | `RWGStaged` | `RWGActive` | **一步到位**。动态波形不允许进入 `Armed` 状态，必须直接激活。 |
| **开关** | `RWGActive` | `RWGArmed` | **关闭 RF 输出**（Disarm）。 |
| **更新** | `RWGActive` | `RWGActive` | **实时更新**。 |

---

## 五、 完整项目结构

```text
catseq_project/
│
├── catseq/                  # Cat-SEQ 核心库包
│   ├── __init__.py          # 定义包的公共API
│   ├── model.py             # 【已实现】核心理论模型 (Morphism, State, Protocol)
│   │
│   ├── states/              # 【已实现】状态词汇表包
│   │   ├── __init__.py
│   │   ├── common.py
│   │   ├── ttl.py
│   │   ├── dac.py
│   │   └── rwg.py
│   │
│   ├── hardware/            # 【已实现】物理规则库包
│   │   ├── __init__.py      # 【待实现】定义全局 Channel 枚举
│   │   ├── base.py
│   │   ├── ttl.py
│   │   ├── dac.py           # 【待实现】
│   │   └── rwg.py
│   │
│   ├── morphisms/           # 【待实现】Morphism 工厂包
│   │   ├── __init__.py
│   │   ├── common.py
│   │   ├── rwg.py
│   │   ├── dac.py
│   │   └── ttl.py
│   │
│   ├── sequence.py          # 【待实现】高级序列构建器 (Sequence Builder)
│   ├── compiler.py          # 【未实现】编译器/调度器
│   │
│   └── backends/            # 【未实现】后端代码生成器包
│       ├── ...
│
└── examples/                # 【未实现】使用示例目录
    └── ...
```

### 组件职责详解 (最终版)

* `model.py`: **理论基石**。定义抽象代数结构。`@` 组合操作是纯粹的数学拼接。
* `states/` (包): **状态词汇表**。定义所有作为静态快照或标记的 `State` 子类。
* `hardware/` (包): **物理规则库**。定义具体硬件类，并提供 `validate_dynamics` 和 `validate_transition` 等验证方法供上层调用。
* `morphisms/` (包): **(待实现)** **Morphism 工TR】**。提供 `Stage()`, `Arm()` 等底层工厂函数，负责执行物理计算和**创建时验证**，生成自洽的 `Morphism` 对象。
* `sequence.py`: **(待实现)** **高级 API / 序列构建器**。提供 `Sequence` 类，它在内部调用 `morphisms` 包的工厂函数，并自动管理状态上下文，为用户提供流畅的链式调用接口，并支持时间点查询 (`get_state_at`)。
* `compiler.py`: **(未实现)** **编译器与调度器**。接收 `Sequence` 对象或 `Morphism` 树，执行**编译时验证**，然后将其翻译为中间事件列表。
* `backends/` (包): **(未实现)** **代码生成器**。将中间事件列表，翻译成最终的目标平台汇编代码。