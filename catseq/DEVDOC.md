# Cat-SEQ: 基于幺半范畴的时序控制框架开发文档

**版本**: 1.0
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
* `dynamics`: 描述过程如何演化的参数（例如 `WaveformParams`）。

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
这是最复杂的状态系统，我们将其分解为“过程描述”和“状态快照”两部分。

#### 过程描述对象
* `WaveformParams`: **由 `Morphism` 持有**，完整描述一个动态波形过程。
    * `sbg_id: int`
    * `freq_coeffs: Tuple[Optional[float], ...]` (泰勒系数 F0-F3)
    * `amp_coeffs: Tuple[Optional[float], ...]` (泰勒系数 A0-A3)
    * `initial_phase: Optional[float]`
    * `phase_reset: Optional[bool]`
    * `required_ramping_order: int` (计算属性)
    * `is_dynamical: bool` (计算属性)

#### 状态快照对象
* `StaticWaveform`: **由 `DDSActive` 状态持有**，描述一个 SBG 的瞬时参数。
    * `sbg_id: int`
    * `freq: float`
    * `amp: float`
    * `phase: float`

#### 状态机
* `DDSState(State)`: DDS 状态的基类。
* `DDSReady(DDSState)`: 通道已初始化，载波已设定，等待配置。
* `DDSStaged(DDSState)`: 波形参数已写入暂存寄存器，但未生效。
* `DDSArmed(DDSState)`: 参数已生效（`PAR_UPD`已触发），SBG 内部开始运行，但 RF 输出关闭。
* `DDSActive(DDSState)`: RF 信号正在有效输出。

---

## 四、 状态机定义 (State Machine Definitions)

状态转换的合法性由 `hardware` 层中具体硬件类的 `validate_transition` 方法来保证。

### 1. TTL 状态机
TTL 的状态转换非常灵活，在类型正确的前提下，几乎所有转换都被允许。

| 起始状态 (From)             | 目标状态 (To)               | 条件/约束                               |
| --------------------------- | --------------------------- | --------------------------------------- |
| `Uninitialized`             | `TTLInput` / `On` / `Off`   | 初始化。                                |
| `TTLInput` / `On` / `Off`   | `TTLInput` / `On` / `Off`   | 允许在任何已配置状态之间自由转换。      |

### 2. DAC 状态机

| 起始状态 (From)             | 目标状态 (To)               | 条件/约束                               |
| --------------------------- | --------------------------- | --------------------------------------- |
| `Uninitialized`             | `DACOff` / `DACStatic`      | 初始化。                                |
| `DACOff`                    | `DACStatic`                 | 打开输出。                              |
| `DACStatic`                 | `DACOff`                    | 关闭输出。                              |
| `DACStatic`                 | `DACStatic`                 | 改变电压。                              |

### 3. DDS/RWG 状态机
这是最严格的状态机，它强制执行了硬件的操作流程。

| 起始状态 (From)             | 目标状态 (To)               | 条件/约束                                                                |
| --------------------------- | --------------------------- | ------------------------------------------------------------------------ |
| `Uninitialized`             | `DDSReady`                  | **唯一**的初始化路径。                                                   |
| `Ready`/`Staged`/`Armed`/`Active` | `DDSStaged`                 | 允许在任何已配置状态下，为下个操作准备/暂存新的波形参数。                  |
| `DDSStaged`                 | `DDSArmed`                  | **让参数生效**。`waveforms` 必须与 `from_state` 一致。 **不允许**包含动态波形。 |
| `DDSActive`                 | `DDSArmed`                  | **关闭 RF 输出**（Disarm）。`waveforms` 必须与 `from_state` 一致。           |
| `DDSArmed`                  | `DDSActive`                 | **打开 RF 输出**。`waveforms` 必须与 `from_state` 一致。                     |
| `DDSStaged`                 | `DDSActive`                 | **一步到位**。允许直接从暂存状态激活 RF 输出。 `waveforms` 必须与 `from_state` 一致。 |
| `DDSActive`                 | `DDSActive`                 | **实时更新**。`waveforms` 可以改变。需要进行连续性检查。                     |

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
│       ├── __init__.py
│       └── rtmq_generator.py
│
└── examples/                # 【未实现】使用示例目录
    └── simple_sequence.py
```

### 组件职责详解

* `model.py`: **理论基石**。定义了整个系统的抽象代数结构和通用规则。完全独立，零依赖。
* `states/` (包): **状态词汇表**。定义所有具体的 `State` 子类。
* `hardware/` (包): **物理规则书**。
    * `base.py`: 定义所有硬件类的抽象基类 `BaseHardware`。
    * `ttl.py`, `dac.py`, `rwg.py`: 定义具体硬件类，实现 `validate_transition` 等验证方法。
    * `__init__.py`: 定义全局 `Channel` 枚举，实例化并注册系统中所有的硬件资源。
* `dsl.py`: **(未实现)** **用户 API / Morphism 工厂**。提供 `Play()`, `RampDAC()` 等简单函数，负责进行物理计算（`dom`+`dynamics`+`duration` -> `cod`），调用 `hardware` 层的 `validate_dynamics`，并最终创建出自洽的、合法的 `Morphism` 对象。
* `compiler.py`: **(未实现)** **编译器与调度器**。接收 `DSL` 构建的 `Morphism` 树，执行复杂的跨 `Morphism` 验证（如相位重置检查），然后将其“扁平化”为按板卡和时间戳排序的中间事件列表。
* `backends/` (包): **(未实现)** **代码生成器**。将编译器生成的中间事件列表，翻译成最终的目标平台汇编代码（如 RTMQv2）。