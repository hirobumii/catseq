# RWG 功能实现计划

## 1. 目标

在 CatSeq 框架中添加对 RWG（实时波形发生器）硬件的完整支持。此实现将严格遵守框架现有的核心设计原则，提供一个强大、直观且类型安全的 API。

## 2. 核心设计原则

经过详细讨论，我们确定了以下不可违背的设计原则：

1.  **统一的 `Channel` 抽象**: 框架的核心可操作对象是 `Channel`。为了无歧义地支持不同类型的硬件，`Channel` 的定义将包含一个 `channel_type` 字段。
    *   TTL 通道: `Channel(board, 0, ChannelType.TTL)`
    *   RWG 端口: `Channel(board, 0, ChannelType.RWG)`

2.  **完全静态分配**: 编译器不进行任何形式的动态资源分配。所有关于使用哪个SBG的决策都由用户在代码中**显式**、**静态**地做出。

3.  **清晰的组合规则**:
    *   `|` (并行组合): 仅用于组合作用在**不同 `Channel`** 上的 `Morphism`。
    *   `@` (严格串行): 用于连接两个**完全定义好**的 `Morphism`，它会严格检查边界状态的连续性。
    *   `>>` (演化串行): 用于**构建连续变化**的序列，它会自动将前一个 `Morphism` 的结束状态作为后一个的起始状态，并以此计算斜率等参数。

## 3. 用户 API 设计 (`hardware/rwg.py`)

为了提供符合用户习惯的、便捷的API，我们将提供以下高级函数：

### 3.1. 辅助类型

```python
from dataclasses import dataclass

@dataclass
class RampTarget:
    """定义一个SBG的斜坡目标"""
    sbg_id: int
    target_freq: float
    target_amp: float
```

### 3.2. 高级 API 函数

```python
from typing import List

# 初始化一个或多个音调的起始状态
def set_state(channel: Channel, targets: List[RampTarget]) -> Morphism:
    # ...

# 创建一个线性斜坡
def linear_ramp(channel: Channel, targets: List[RampTarget], duration_us: float) -> Morphism:
    # ...

# 保持当前状态一段时间
def hold(channel: Channel, duration_us: float) -> Morphism:
    # ...
```

### 3.3. 用户代码示例

```python
from catseq.hardware import rwg
from catseq.types.common import Board, Channel, ChannelType

# 定义硬件资源
rwg_board = Board("rwg0")
rwg_ch0 = Channel(rwg_board, 0, ChannelType.RWG)

# 构建一个连续变化的序列
# 1. 设置SBG 0的初始状态为 10MHz, 0.5振幅
start_op = rwg.set_state(rwg_ch0, targets=[
    rwg.RampTarget(sbg_id=0, target_freq=10, target_amp=0.5)
])

# 2. 在10us内，将SBG 0线性地变到12MHz, 0.6振幅
ramp1 = rwg.linear_ramp(rwg_ch0, targets=[
    rwg.RampTarget(sbg_id=0, target_freq=12, target_amp=0.6)
], duration_us=10)

# 3. 保持状态5us
hold_op = rwg.hold(rwg_ch0, duration_us=5)

# 4. 在5us内，将SBG 0变到15MHz, 0.7振幅，同时将SBG 1从当前状态变到20MHz, 0.4振幅
ramp2 = rwg.linear_ramp(rwg_ch0, targets=[
    rwg.RampTarget(sbg_id=0, target_freq=15, target_amp=0.7),
    rwg.RampTarget(sbg_id=1, target_freq=20, target_amp=0.4)
], duration_us=5)

# 使用 `>>` 将所有操作流畅地串联起来
final_sequence = start_op >> ramp1 >> hold_op >> ramp2
```

## 4. 实现步骤

### 第一步：修改类型系统 (`catseq/types/`)

1.  **`common.py`**:
    *   创建 `ChannelType(Enum)`，包含 `TTL` 和 `RWG`。
    *   为 `Channel` dataclass 添加 `channel_type: ChannelType` 字段。
    *   在 `OperationType(Enum)` 中为RWG添加新的原子操作类型 (`RWG_INIT`, `RWG_LOAD_COEFFS`, `RWG_UPDATE_PARAMS`)。
2.  **`rwg.py`**:
    *   创建此新文件。
    *   定义 `RWGState` 基类及子类 (`RWGUninitialized`, `RWGReady`, `RWGActive`)。
    *   定义 `StaticWaveform` 和 `WaveformParams` 两个 dataclass。
3.  **`__init__.py`**:
    *   从 `common`, `ttl`, `rwg` 中导出所有公开的类型。

### 第二步：实现高级 API (`catseq/hardware/rwg.py`)

1.  创建 `catseq/hardware/rwg.py` 文件。
2.  实现 `set_state`, `linear_ramp`, `hold` 等用户接口。
3.  这些函数将作为 `MorphismBuilder`，它们的核心逻辑是：接收 `start_state`，计算斜率，并构建出包含 `WaveformParams` 列表的底层 `Morphism`。

### 第三步：实现原子操作 (`catseq/atomic.py`)

1.  添加供 `hardware/rwg.py` 调用的底层原子操作创建函数。
2.  `rwg_init(channel, carrier_freq)`: 创建 `RWG_INIT` 类型的 `AtomicMorphism`。
3.  `rwg_play(channel, params: List[WaveformParams], duration_us)`: 创建包含 `RWG_LOAD_COEFFS` 和 `RWG_UPDATE_PARAMS` 两种 `AtomicMorphism` 的组合。

### 第四步：实现编译器逻辑 (`catseq/compilation/compiler.py`)

1.  在编译器中添加对 `RWG_*` 系列 `OperationType` 的处理逻辑。
2.  **`RWG_INIT`**: 根据 `channel` 推断出 RF 端口，检查是否已初始化，若未，则生成初始化DDS的OASM指令。
3.  **`RWG_LOAD_COEFFS`**: **核心逻辑**。遍历 `params` 列表，对每个 `WaveformParams`：
    *   根据文档公式，实现物理单位到机器单位的泰勒系数转换。
    *   生成写入 `FT*` 和 `AP*` 等CSRs的OASM指令序列。
4.  **`RWG_UPDATE_PARAMS`**: 根据 `channel` 推断出 RF 端口，生成触发 `PAR_UPD` 的OASM指令。

### 第五步：编写测试 (`tests/`)

1.  **单元测试**:
    *   `test_rwg_types.py`: 验证新的类型和 `Channel` 的行为。
    *   `test_rwg_api.py`: 测试 `hardware.rwg` 中的高级API函数及其组合 (`>>`, `@`, `|`) 规则。
    *   `test_rwg_compiler.py`: 独立测试RWG的 `Morphism` 能否被正确编译成预期的OASM调用序列。
2.  **集成测试**:
    *   `test_rwg_pipeline.py`: 编写一个完整的端到端测试，覆盖从API调用到最终OASM生成（或模拟执行）的全过程。
