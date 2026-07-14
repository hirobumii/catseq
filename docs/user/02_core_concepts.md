# 2. 核心概念 (Core Concepts)

理解 `catseq` 的几个核心概念，是高效使用这个库的关键。`catseq` 的设计借鉴了范畴论的思想，旨在提供一个严谨且灵活的序列构建框架。

## Morphism: 时序的积木

`Morphism` (态射) 是 `catseq` 中最核心、最基本的概念。你可以把它理解为一块“时序积木”。

*   **它是什么？** 一个 `Morphism` 代表了在一个或多个硬件通道上，持续一段**确定时间**的操作。 
*   **它有什么？** 它内部包含了这段时间内所有通道上发生的一个或多个原子操作（`AtomicMorphism`）。
*   **关键特性**: 同一个 `Morphism` 中的所有通道，其操作总时长必须是**完全相等**的。这是并行组合的基础。

几乎所有的 `catseq` 操作最终都会生成一个 `Morphism`。

## Channel 和 Board: 硬件的抽象

*   **`Board`**: 代表一个物理硬件板卡，它有一个唯一的ID（例如，`"main_board"`）。
*   **`Channel`**: 代表板卡上的一个具体通道（例如，TTL通道0，RWG通道1）。它总是与一个 `Board` 相关联，并且拥有自己的类型 (`ChannelType`) 和通道号 (`local_id`)。

这两个对象共同构成了硬件的拓扑结构，让 `catseq` 知道每个操作应该作用于哪个具体的物理目标。

## 组合: 构建复杂序列的艺术

组合是 `catseq` 的威力所在。通过简单的操作符，您可以将简单的 `Morphism` 像乐高积木一样拼装成复杂的序列。

### 串行组合: `>>`

`>>` 操作符将两个 `Morphism` 首尾相连。

```python
# 序列 C 是 A 后面紧跟着 B
C = A >> B 
```

*   **状态推断**: `>>` 非常智能，它会自动推断 `B` 的起始状态应该是什么，即 `A` 的结束状态。你不需要手动管理状态的流转。
*   **时间累加**: 最终序列 `C` 的总时长是 `A` 和 `B` 的时长之和。

### 并行组合: `|`

`|` 操作符让两个 `Morphism` 在时间上同时发生。

```python
# 序列 C 是 A 和 B 同时执行
C = A | B
```

*   **通道**：用于并联的两个 `Morphism` 必须操作完全不同的通道，否则会报错。
*   **自动对齐**: 如果 `A` 和 `B` 的时长不同，`catseq` 会自动在较短的那个序列末尾填充一段 `identity` (逻辑等待)，使其时长与较长的序列对齐。这是确保所有并行通道时长严格相等的关键机制。

## State: 确保操作的有效性

`catseq` 是一个有状态的框架。它会追踪每个硬件通道在序列演进过程中的状态。例如：

*   一个 `TTL` 通道的状态可以是 `TTLState.ON` 或 `TTLState.OFF`。
*   一个 `RWG` 通道的状态可以是 `RWGUninitialized` (未初始化), `RWGReady` (已就绪), 或 `RWGActive` (正在播放波形)。

在定义操作时，`catseq` 会检查当前状态是否是此操作的合法起始状态。例如，你不能在一个已经是 `ON` 状态的 TTL 通道上再次执行 `on()` 操作。这种机制可以帮助你在编译前就发现大量逻辑错误。

## MorphismDef：可编译的 Morphism Template

`MorphismDef` 是 `MorphismTemplate` 的兼容拼写。它不是 Python generator，
也不会在 CPython 中接收 `start_state` 后构造 Lane。模板具有自由 Channel
slot；绑定 Channel 时，Rust Morphism arena 生成引用共享模板体的
`Instantiate` 节点。

用户可以直接用 Atomic Morphism 组合更复杂的模板：

```python
from catseq.hardware.ttl import hold, set_high, set_low
from catseq.morphism import MorphismDef, morphism_template


@morphism_template
def pulse(duration: float) -> MorphismDef:
    return set_high() >> hold(duration) >> set_low()
```

编译器将函数体保留为 `Serial(set_high, Wait(duration), set_low)`，调用点
只保存参数和 `Instantiate` 引用。入口中可使用
`{my_channel: pulse(duration)}` 完成绑定。输入/输出状态由 Morphism Effect
沿 Serial 边隐式传递，不出现在 Python 函数参数中。

`@atomic_morphism` 仅供硬件驱动/Intrinsic Registry 声明不可再分解的叶子；
普通用户应通过 `@morphism_template` 组合已注册的原子操作。
