# CatSeq V2 Architecture Specification

**Version:** 3.0 (Final)
**Model:** The Trigger-Wait Model (Pure Event Stream)
**Context:** High-Performance Quantum Control Systems (FPGA/ASIC)

This document serves as the canonical reference for the CatSeq V2 algebraic and physical model. It supersedes all previous "block-based" or "dual-track" designs.

---

## 1. 核心公理 (Core Axioms)

CatSeq V2 的物理模型建立在 **"瞬时触发 + 显式等待"** 的基础之上。

### Axiom 1: Everything is Instantaneous (除 Wait 外)
所有的原子硬件指令（Atomic Instructions）在代数结构上都是 **瞬时** 的 ($d=0$)。
* **指令即触发**: 无论是加载参数 (`LOAD`) 还是触发波形 (`PLAY`)，在代数层均视为 $t=0$ 时刻完成。
* **无体积**: 操作本身不占据代数时间轴。

### Axiom 2: Only Wait Defines Duration
只有 `Identity(t)` (即 `Wait(t)`) 指令具有代数时长 ($d=t$)。
* **唯一时间驱动**: 它是唯一能推进逻辑时间戳（Timestamp）的操作。
* **隐式定义物理时长**: 物理波形的持续时间，完全由用户在 `Trigger` 指令后跟随的 `Wait` 指令长度来隐式定义。

---

## 2. 指令分类学 (Instruction Taxonomy)

根据物理特性（是否产生物理信号）和调度特性（总线延迟），将 `OpCode` 分为三类：

### Type A: 状态配置指令 (Configuration Ops)
* **语义**: 修改控制器的影子寄存器、内存或状态机参数。无直接物理信号输出。
* **物理消耗**: **显著的总线延迟 (Bus Latency)**。数据传输需要时钟周期。
* **调度属性**: **Floating (浮动)**。逻辑上依附于最近的锚定点。
* **例子**: `RWG_LOAD_COEFFS`, `RWG_SET_PHASE`, `RWG_SET_FREQ`.

### Type B: 触发/动作指令 (Action Ops)
* **语义**: 将当前寄存器状态提交（Commit）到物理端口，或触发波形引擎。
* **物理消耗**: **极小的总线延迟 (Minimal Latency)**。通常仅需发送一个 Trigger 信号。
* **调度属性**: **Anchored (锚定)**。其执行时刻即为物理事件发生的绝对时刻 (Timestamp)。
* **例子**: `RWG_PLAY` (Trigger Only), `TTL_ON`, `TTL_OFF`, `ADC_CAPTURE`.

### Type C: 时间指令 (Timing Ops)
* **语义**: 推进全局逻辑时钟，并在物理层产生空闲等待。
* **物理消耗**: 无总线占用，纯粹的时间流逝。
* **例子**: `Wait`, `Sync`.

---

## 3. 编译器与调度模型 (Compiler & Scheduling)

编译器不再计算波形体积，而是负责 **总线延迟约束检查 (Bus Latency Constraints)** 和 **序列化 (Linearization)**。

### 3.1 线性化模型
输入序列：
$$ \dots \to Op_{cfg} \to Op_{act} \to Wait(T) \to \dots $$

* $Op_{cfg}$ (Type A): $d=0$
* $Op_{act}$ (Type B): $d=0$
* $Wait(T)$ (Type C): $d=T$

编译器将其映射到物理时间轴，处理 **指令发射开销 (Instruction Issue Overhead)**。

### 3.2 延迟隐藏与冲突检测 (Latency Hiding & Conflict)

由于 $Op_{cfg}$ 和 $Op_{act}$ 逻辑上同时发生 ($t=0$)，但物理总线必须串行发送。

**调度逻辑**:
1.  **堆积**: 编译器收集连续的 $d=0$ 指令块。
2.  **累加**: 计算该块的总总线耗时 $\Sigma Latency$。
3.  **约束检查**: 检查紧随其后的 `Wait(T)` 窗口是否足够大。
    * **Pass**: $\Sigma Latency \le T$。指令可以在这段等待时间内从容发送。
    * **Fail (Underflow)**: $\Sigma Latency > T$。用户试图在极短时间内塞入过多指令，导致物理总线阻塞，破坏时序。

**示例 (Latency Hiding)**:
```python
# 用户意图：播放A，期间加载B
Trigger(A) >> Load(B_Params) >> Wait(1000ns) >> Trigger(B)
```
* `Trigger(A)`: 耗时 1 cycle。
* `Load(B)`: 耗时 20 cycles。
* `Wait(1000ns)`: 提供 1000 cycles 窗口。
* **结果**: `Load(B)` 实际上是在 `Trigger(A)` 之后的物理空隙中发送的。这就实现了“边放边载”。

---

## 4. 实现规范 (Implementation Specs)

### 4.1 OpCode Metadata (Python Layer)

```python
from enum import Enum

class OpType(Enum):
    CONFIG = 1  # Load, Set (High Latency)
    ACTION = 2  # Play, Trigger (Low Latency, Anchored)
    TIMING = 3  # Wait

# 指令元数据表
OP_SPECS = {
    OpCode.RWG_LOAD_COEFFS: {
        "type": OpType.CONFIG,
        "latency": 20, # cycles (Estimated bus cost)
    },
    OpCode.RWG_PLAY: {
        "type": OpType.ACTION,
        "latency": 1,  # cycles
    },
    OpCode.TTL_ON: {
        "type": OpType.ACTION,
        "latency": 1,
    },
    OpCode.IDENTITY: {
        "type": OpType.TIMING,
        "latency": 0
    }
}
```

### 4.2 API Design Pattern

用户 API 应封装底层的“配置-触发-等待”模式，提供符合直觉的接口。

```python
# catseq/v2/rwg.py

def load(channel, data):
    # d=0, Type A
    return RustMorphism.atomic(ctx, channel, 0, OpCode.RWG_LOAD, data)

def trigger(channel):
    # d=0, Type B
    return RustMorphism.atomic(ctx, channel, 0, OpCode.RWG_PLAY, b"")

def wait(duration):
    # d=duration, Type C
    cycles = time_to_cycles(duration)
    return RustMorphism.atomic(ctx, channel, cycles, OpCode.IDENTITY, b"")

# Standard Pattern
def play_waveform(channel, data, duration):
    """
    Standard usage: Load -> Trigger -> Wait.
    The 'duration' here protects the waveform from being interrupted 
    by subsequent instructions.
    """
    return load(channel, data) >> trigger(channel) >> wait(duration)

# Pipeline Pattern (Latency Hiding)
def play_continuous(channel, current_data, next_data, duration):
    """
    Advanced usage: Trigger current -> Load next (hidden) -> Wait
    """
    return trigger(channel) >> load(channel, next_data) >> wait(duration)
```

---

## 5. 禁区 (Anti-Patterns)

1.  **禁止给 Action 指令赋予 Duration**:
    * ❌ `ctx.atomic(..., duration=100, OpCode.RWG_PLAY, ...)`
    * Rust 后端会误以为该指令独占了通道，导致无法进行并行优化或错误的冲突检测。
    * **修正**: `RWG_PLAY` 的 duration 必须为 0。

2.  **禁止依赖隐式时序**:
    * 不要假设 `Load` 不需要时间。如果 `Load` 后面的 `Wait` 太短（例如 `Wait(0)`），编译器应报错或发出警告（总线冲突）。

3.  **禁止在 Rust 层做语义解释**:
    * Rust 层只负责 `Duration` 的加法和 `OpCode` 的透传。所有关于 Latency 的计算和约束检查应在 Python 层（Compiler Pass）完成。