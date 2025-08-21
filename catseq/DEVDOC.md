# Cat-SEQ: 基于幺半范畴的时序控制框架开发文档

**版本**: 2.0 (设计演进版)
**日期**: 2025-08-21

## 一、 核心抽象：幺半范畴 (Monoidal Category)

Cat-SEQ 框架的理论基石是**范畴论**，具体而言是**幺半范畴**。这一选择旨在将时序编程从传统的“命令硬件如何做”的**指令式**思想，转变为“描述实验是什么”的**声明式**思想。我们通过建立物理概念到范畴论元素的精确映射，获得了一个代数结构清晰、组合能力强大的时序描述系统。

### 1. 对象 (Object)
在 Cat-SEQ 中，一个**对象 (Object)** 代表了**整个实验系统在某一瞬时（snapshot）的完整状态**。它不是指单个硬件，而是所有相关硬件资源及其状态的集合。

在实现上，这是一个由 `(硬件资源, 具体状态)` 对组成的元组 (Tuple)，例如：
`((Channel.RWG_RF0, DDSActive(...)), (Channel.TTL_0, TTLOutputOn()), ...)`

### 2. 态射 (Morphism)
**态射 (Morphism)** 是我们框架的原子单元，它代表了一个**持续一段时间的物理过程**。任何时序片段，无论是一个简单的等待，还是一个复杂的波形播放，都被统一抽象为态射。

一个态射 `f` 是一个从**域对象 (domain)** 到**靶对象 (codomain)** 的映射，记作 `f: dom -> cod`。它具有以下核心属性：
* `dom`: 过程开始前的系统状态 (一个**对象**)。
* `cod`: 过程结束时的系统状态 (一个**对象**)。
* `duration`: 过程的持续时间（秒）。
* `dynamics`: **(设计演进)** 描述过程如何演化的参数。例如，对于DDS通道，它持有 `WaveformParams` 或 `StaticWaveform` 对象。这是将“过程”从“状态”中分离的关键。

### 3. 复合 (Composition)
**复合 (Composition)** 对应**时序的顺序执行**。给定两个态射 `f: A -> B` 和 `g: B -> C`，它们的复合 `f @ g` 形成了一个新的态射 `h: A -> C`。复合的先决条件是前一个态射的 `codomain` 必须与后一个态射的 `domain` 完全匹配。其 `duration` 是两者之和。

### 4. 张量积 (Tensor Product)
**张量积 (Tensor Product)** 对应**时序的并行执行**。给定两个作用在**不相交**硬件资源上的态射 `f: A -> B` 和 `g: C -> D`，它们的张量积 `f | g` 形成了一个新的态射 `h: (A ⊗ C) -> (B ⊗ D)`。其 `duration` 取两者中的最大值。

---

## 二、 类型系统：安全与灵活的基石

为了将上述抽象模型安全、可靠地在 Python 中实现，我们严重依赖其强大的类型系统 (`typing`)。

* **`Generic[ChannelT]`**: `Morphism` 类被定义为泛型，使其能够与任意类型的硬件资源协同工作，保证了核心模型的通用性。

* **`TypeVar` 与 `bound`**: 我们通过 `ChannelT = TypeVar('ChannelT', bound=ResourceIdentifier)` 声明了类型变量 `ChannelT`。这里的 `bound` 是一个强制契约，它要求任何用于 `Morphism` 的具体硬件资源类型，都必须遵循 `ResourceIdentifier` 协议。这是保证泛型安全的核心机制。

* **`Protocol`**: 我们使用协议（`ResourceIdentifier`, `HardwareInterface`）来定义硬件必须遵守的接口契约，而不是依赖具体的类继承。这使得 `model.py` 能够完全独立，无需导入任何具体的硬件实现，达到了最大程度的解耦。

* **`typing.Self`**: 在 `BaseHardware` 等类中，我们使用 `Self` 来注解返回自身实例的方法，这是 Python 3.11+ 的最佳实践，能提供更精确的类型推断，尤其是在子类中。

---

## 三、 状态定义 (State Definitions)

`State` 是描述硬件瞬时静态快照的不可变数据类 (`frozen=True dataclass`)。

### 1. 通用状态 (`states/common.py`)
* `Uninitialized`: 代表硬件上电后、被软件配置前的初始状态。

### 2. TTL 状态 (`states/ttl.py`)
* `TTLState(State)`: TTL 状态的基类。
* `TTLInput(TTLState)`: 配置为输入模式。
* `TTLOutputOn(TTLState)`: 配置为输出模式，且电平为高。
* `TTLOutputOff(TTLState)`: 配置为输出模式，且电平为低。

### 3. DAC 状态 (`states/dac.py`)
* `DACState(State)`: DAC 状态的基类。
* `DACOff(DACState)`: 输出被禁用或处于高阻态。
* `DACStatic(DACState)`: 输出一个稳定的直流电压。
    * `voltage: float`: 输出的电压值（伏特）。

### 4. DDS/RWG 状态 (`states/dds.py`)

#### 4.1 设计演进：从“状态持有过程”到“状态与过程分离”
我们最初的设计试图让 `State` 对象（如 `DDSActive`）持有完整的波形过程描述（`WaveformParams`，包含斜坡系数）。经过深入讨论，我们发现这破坏了 `State` 作为“静态快照”的纯粹性，并使 `Morphism` 的组合在概念上变得模糊。

> **最终原则**：`State` 只描述某一瞬时的**静态快照**。`Morphism` 的 `dynamics` 字段负责携带完整的**动态过程描述**。

#### 4.2 最终数据结构定义

* **过程描述对象 (Process Descriptions)**: **由 `Morphism` 的 `dynamics` 字段持有**。
    * `WaveformParams`: 描述一个**动态**波形过程（如斜坡）。包含泰勒系数和 `is_dynamical` 等属性。
    * `StaticWaveform`: 描述一个**静态**波形过程（如保持恒定频率）。只包含瞬时值。

* **状态机 (State Machine)**:
    * `DDSState(State)`: DDS 状态的基类。
    * `DDSReady(DDSState)`: 通道已初始化，载波已设定。持有 `carrier_freq`。
    * `DDSStaged(DDSState)`: **(无数据标记)** 表示参数已写入暂存器。只持有 `carrier_freq`。
    * `DDSArmed(DDSState)`: **(仅限静态)** 表示一个**静态**波形的参数已生效，但 RF 输出关闭。持有 `Tuple[StaticWaveform, ...]`。
    * `DDSActive(DDSState)`: RF 信号正在有效输出。持有 `Tuple[StaticWaveform, ...]` 作为物理快照。

---

## 四、 验证模型与状态机

#### 4.1 设计演进：从“组合时验证”到“分层验证”
我们最初的思路是将所有验证逻辑都放在 `Morphism` 组合 (`@`) 时调用的 `validate_transition` 方法中。但经过讨论，我们确立了一个更健壮、职责更清晰的**分层验证模型**。

> **最终原则**：验证发生在**创建时**、**组合时**和**编译时**三个阶段。

1.  **创建时 (DSL 层)**: `Morphism` 的“智能工厂”。负责物理计算（`dom`+`dynamics`+`duration`->`cod`），并调用 `hardware.validate_dynamics` 验证过程参数自身的合法性。**保证每个被创建的 `Morphism` 都是自洽且合法的**。
2.  **组合时 (`@` 操作符)**: `Morphism` 的组合。只进行最纯粹的数学检查，即 `f.cod == g.dom`。所有复杂的验证逻辑已从此移除。
3.  **编译时 (Compiler 层)**: 唯一的全局上下文持有者。负责执行需要跨 `Morphism` 边界的复杂验证（例如 `enforce_continuity` 策略下的相位重置检查）。

#### 4.2 最终状态机定义
现在，状态转换的合法性由 `DSL` 层在创建 `Morphism` 时，通过查询 `hardware` 层的规则来保证。以下是 `DSL` 层需要遵守的合法转换路径。

* **TTL 与 DAC 状态机**: (与旧版定义相同，保持不变)

* **DDS/RWG 状态机 (最终版)**:
    该状态机区分了静态和动态两种工作流。

| 流程类型 | 起始状态 (From) | 目标状态 (To) | `Morphism.dynamics` 类型 | 备注/约束                                                                   |
| :--- | :--- | :--- | :--- |:--------------------------------------------------------------------------|
| 初始化 | `Uninitialized` | `DDSReady` | `None` | 唯一的初始化路径。                                                          |
| **静态** | `DDSReady` | `DDSStaged` | `Tuple[StaticWaveform, ...]` | 暂存一个静态波形。                                                          |
| **静态** | `DDSStaged` | `DDSArmed` | `None` | 让暂存的静态波形生效。                                                      |
| **静态** | `DDSArmed` | `DDSActive` | `None` | 打开 RF 输出。                                                              |
| **动态** | `DDSReady` | `DDSStaged` | `Tuple[WaveformParams, ...]` | 暂存一个动态波形。                                                          |
| **动态** | `DDSStaged` | `DDSActive` | `None` | **一步到位**。动态波形不允许进入 `Armed` 状态，必须直接激活。                  |
| 通用 | `DDSActive` | `DDSActive` | `StaticWaveform` / `WaveformParams` | **实时更新**。                                                              |
| 通用 | `DDSActive` | `DDSReady` | `None` | 关闭通道 (如果 `allow_disable` 策略允许)。                                     |

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
│   │   └── dds.py
│   │
│   ├── hardware/            # 【已实现】物理规则与硬件定义包
│   │   ├── __init__.py      # 【待实现】定义全局 Channel 枚举
│   │   ├── base.py
│   │   ├── ttl.py
│   │   ├── dac.py           # 【待实现】
│   │   └── rwg.py
│   │
│   ├── dsl.py               # 【未实现】用户接口/Morphism 工厂
│   ├── compiler.py          # 【未实现】编译器/调度器
│   │
│   └── backends/            # 【未实现】后端代码生成器包
│       ├── ...
│
└── examples/                # 【未实现】使用示例目录
    └── ...
```

### 组件职责详解 (最终版)

* `model.py`: **理论基石**。定义抽象代数结构。其 `@` 组合操作现在是一个纯粹的、只检查端点匹配的数学运算。
* `states/` (包): **状态词汇表**。定义所有具体的 `State` 子类，它们现在是纯粹的静态快照或标记。
* `hardware/` (包): **物理规则库**。
    * 定义具体硬件类，并提供验证方法，如 `validate_dynamics` (验证过程参数) 和 `is_valid_fsm_path` (供 DSL 查询状态机路径合法性)。
    * `__init__.py`: 定义全局 `Channel` 枚举，通过**配置参数**实例化不同“能力”和“策略”的硬件对象。
* `dsl.py`: **(未实现)** **用户 API / 智能工厂**。
    * **核心职责**：将用户的简单意图（如 `RampFreq(...)`）转化为一个**自洽且合法**的 `Morphism` 对象。
    * **内部工作**:
        1.  进行物理计算 (`dom`+`dynamics`+`duration` -> `cod`)。
        2.  调用 `hardware` 层的 `validate_dynamics` 和 `is_valid_fsm_path` 等方法进行**创建时验证**。
* `compiler.py`: **(未实现)** **编译器与调度器**。
    * **核心职责**：接收 `Morphism` 树，将其翻译为中间表示。
    * **新增职责**：作为**最终验证层**，执行需要完整上下文的检查（如 `enforce_continuity` 策略下的相位重置检查）。
* `backends/` (包): **(未实现)** **代码生成器**。将中间表示翻译成目标平台的汇编代码。