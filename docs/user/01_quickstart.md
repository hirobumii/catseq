# 1. 快速上手 (Quickstart)

本文档将通过一个简单的示例，带您快速了解如何使用 `catseq` 来构建和编译一个硬件控制序列。

## `catseq` 是什么？

`catseq` 是一个用于精确描述和编排复杂硬件时序的 Python 库。它通过一种声明式、可组合的方式，让您能够清晰地定义在不同硬件通道（如 TTL、任意波形发生器 RWG）上的操作序列，然后将这个高级描述编译成底层的硬件指令。

## 安装

如果您是在本地开发环境中，请确保您已经通过以下命令安装了 `catseq`：

```bash
pip install -e .
```

## 一个完整的例子

让我们构建一个包含 TTL 和 RWG 通道的简单序列。我们将让一个 TTL 信号输出一个 10µs 的脉冲，同时，一个 RWG 通道被初始化并设置一个初始的正弦波状态。

将以下代码保存为 `my_first_sequence.py`：

```python
from catseq.types.common import Board, Channel, ChannelType
from catseq.hardware import rwg, ttl
from catseq.compilation.compiler import compile_to_oasm_calls, OASM_AVAILABLE

# 1. 定义硬件
# 假设我们有一个主板，上面同时有 TTL 和 RWG 通道
board = Board("main_board")
ch_ttl = Channel(board, 0, ChannelType.TTL)
ch_rwg = Channel(board, 1, ChannelType.RWG)

# 2. 编排序列
# 定义一个 10µs 的 TTL 脉冲
ttl_pulse_seq = ttl.on() >> ttl.hold(10) >> ttl.off()

# 定义一个 RWG 初始化并设置状态的序列
# 注意：rwg.initialize() 和 rwg.set_state() 都是 "MorphismDef"，需要调用才能应用到具体通道上
rwg_setup_seq = rwg.initialize(carrier_freq=100e6) >> rwg.set_state(
    [rwg.InitialTarget(sbg_id=0, freq=10e6, amp=0.5)]
)

# 3. 组合序列
# 使用 | 操作符将两个序列并行组合
# 我们需要将序列定义应用到具体的通道上
final_morphism = ttl_pulse_seq(ch_ttl) | rwg_setup_seq(ch_rwg)

# 4. 编译序列
# 如果 oasm 库可用，编译器会进行成本分析
# 如果不可用，它会跳过并打印警告
if not OASM_AVAILABLE:
    print("警告: OASM 库不可用，将跳过成本分析和汇编生成。 সন
    # 在没有 OASM 的情况下，我们仍然可以查看逻辑调用（但通常是空的）
    # 真实的输出需要完整的编译环境

print("---" 正在编译序列... ---")
# 对于这个简单例子，我们不需要一个真实的 assembler_seq
oasm_calls_by_board = compile_to_oasm_calls(final_morphism)

# 5. 查看结果
print("\n--- 编译完成，生成的 OASM 调用: ---")
for board, calls in oasm_calls_by_board.items():
    print(f"\n[Board: {board.value}]")
    if not calls:
        print("  (无调用生成)")
    for i, call in enumerate(calls):
        print(f"  {i+1}: {call.dsl_func.name} {call.args}")

```

## 代码讲解

1.  **定义硬件**: 我们创建了一个 `Board` 和两个 `Channel`。`Channel` 对象是物理硬件通道的逻辑表示。
2.  **编排序列**: 
    *   我们使用 `ttl.on()`, `ttl.hold(10)`, `ttl.off()` 这些返回 `MorphismDef` 的函数来定义 TTL 序列。`>>` 操作符将它们串联起来。
    *   同理，我们定义了 RWG 的序列。
3.  **组合序列**: 
    *   在组合之前，我们通过 `ttl_pulse_seq(ch_ttl)` 的方式，将抽象的序列“绑定”到具体的通道上，生成一个真正的 `Morphism`。
    *   `|` 操作符将 TTL 和 RWG 的 `Morphism` 并行组合。`catseq` 会自动处理对齐，用等待来填充较短的序列，使它们的总时长相等。
4.  **编译序列**: `compile_to_oasm_calls` 是核心函数，它接收一个 `Morphism`，经过我们之前讨论的多个 Pass，最终生成一个按板卡组织的 OASM 调用列表。
5.  **查看结果**: 打印出的 OASM 调用就是可以发送给硬件执行的底层指令序列。

## 如何运行

在您的终端中，直接运行这个 Python 脚本：

```bash
python my_first_sequence.py
```

您将会看到编译器各 Pass 的日志以及最终生成的 OASM 调用指令。