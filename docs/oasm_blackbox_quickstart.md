# oasm_black_box 快速入门指南

## 概述

`oasm_black_box` 允许你将**纯 OASM 函数**包装为 catseq Morphism，绕过 catseq 的高层抽象，直接控制底层硬件。

## 核心概念

### OASM 函数内部
- **纯 OASM DSL 代码**：只包含 `rwg.ttl.on()`, `rwg.timer()` 等 OASM 调用
- **不包含 catseq 概念**：没有 `Channel`, `State`, `Board` 等
- **rwg 对象自动注入**：由 OASM assembler 提供，无需手动传递

### catseq 包装层
- **`channel_states`**: 声明哪些通道被影响（用于状态管理）
- **`duration_cycles`**: 精确的时钟周期数（用于时序计算）
- **`board_funcs`**: 将 OASM 函数与板卡关联

## 快速示例

### 1. 最简单的例子

```python
from catseq.types.common import Board, Channel, ChannelType
from catseq.types.ttl import TTLState
from catseq.atomic import oasm_black_box

# 定义硬件（catseq 抽象）
board = Board("RWG0")
ch1 = Channel(board, 1, ChannelType.TTL)

# 编写纯 OASM 函数
def my_pulse():
    """纯 OASM 代码 - 生成 10μs 脉冲"""
    rwg.ttl.on(1)
    rwg.timer(2500, wait=False)  # 10μs @ 250MHz
    rwg.hold()
    rwg.ttl.off(1)

# 包装为 Morphism
pulse = oasm_black_box(
    channel_states={
        ch1: (TTLState.OFF, TTLState.OFF)  # 开始OFF，结束OFF
    },
    duration_cycles=2503,  # 3个指令 + 2500 cycles
    board_funcs={
        board: my_pulse  # 函数引用
    }
)

# 使用
sequence = some_morphism @ pulse @ another_morphism
```

### 2. 带参数的例子

```python
def configurable_pulse(duration_cycles: int, channel_id: int):
    """带参数的 OASM 函数"""
    rwg.ttl.on(channel_id)
    rwg.timer(duration_cycles, wait=False)
    rwg.hold()
    rwg.ttl.off(channel_id)

# 包装时传递参数
pulse = oasm_black_box(
    channel_states={ch1: (TTLState.OFF, TTLState.OFF)},
    duration_cycles=5002,
    board_funcs={board: configurable_pulse},
    user_args=(5000, 1),  # 传递给 OASM 函数的参数
)
```

### 3. 多通道控制

```python
def multi_channel_burst(mask: int, duration: int):
    """使用位掩码控制多个通道"""
    rwg.ttl.set(mask)  # 同时开启多个通道
    rwg.timer(duration, wait=False)
    rwg.hold()
    rwg.ttl.set(0x00)  # 关闭所有

# 为所有受影响的通道声明状态
burst = oasm_black_box(
    channel_states={
        ch1: (TTLState.OFF, TTLState.OFF),
        ch2: (TTLState.OFF, TTLState.OFF),
    },
    duration_cycles=10002,
    board_funcs={board: multi_channel_burst},
    user_args=(0x03, 10000),  # mask=0x03 (通道0+1)
)
```

### 4. 使用硬件循环

```python
def repeated_pulse(ch_id: int, duration: int, count: int):
    """硬件循环：重复生成脉冲"""
    from oasm.rtmq2 import for_, end, R

    for_(R[1], count)  # 循环 count 次

    # 循环体
    rwg.ttl.on(ch_id)
    rwg.timer(duration, wait=False)
    rwg.hold()
    rwg.ttl.off(ch_id)

    end()

# 计算时长包括循环开销
# 公式: 15 + count * (26 + body_cycles)
body_cycles = 2 + duration
total = 15 + count * (26 + body_cycles)

loop_pulse = oasm_black_box(
    channel_states={ch1: (TTLState.OFF, TTLState.OFF)},
    duration_cycles=total,
    board_funcs={board: repeated_pulse},
    user_args=(1, 1000, 10),  # 10次重复
)
```

## 关键约束

### 1. 独占板卡
Black box 在执行期间**独占整个板卡**：

```python
# ❌ 错误 - 同一板卡上时间重叠
bb = oasm_black_box(...)  # t=0~1000 cycles
other = ttl_on(ch_same_board)  # 假设 t=500
conflict = bb | other  # 编译时报错！

# ✅ 正确 - 时间不重叠
other = identity(1000/250e6) >> ttl_on(ch_same_board)  # t≥1000
safe = bb | other  # 编译成功
```

### 2. 精确时长计算
你必须**手动计算并准确提供** `duration_cycles`：

```python
# 计算示例
# - 3 个 ttl 操作：3 cycles
# - 1 个 timer/hold：2500 cycles
# 总计：2503 cycles
duration_cycles = 2503
```

### 3. 准确状态声明
`channel_states` 必须真实反映你的代码：

```python
# 如果你的代码让通道从 OFF 变为 ON
channel_states = {
    ch1: (TTLState.OFF, TTLState.ON)  # 必须准确
}
```

## 完整工作流程

### 步骤 1: 编写 OASM 函数

```python
def my_oasm_code():
    """纯 OASM - 无 catseq 抽象"""
    rwg.ttl.on(1)
    rwg.timer(2500, wait=False)
    rwg.hold()
    rwg.ttl.off(1)
```

### 步骤 2: 计算时长

```python
# 指令数 + timer 时间
duration = 3 + 2500  # = 2503 cycles
```

### 步骤 3: 声明状态

```python
channel_states = {
    ch1: (TTLState.OFF, TTLState.OFF)
}
```

### 步骤 4: 创建 black box

```python
bb = oasm_black_box(
    channel_states=channel_states,
    duration_cycles=duration,
    board_funcs={board: my_oasm_code}
)
```

### 步骤 5: 组合使用

```python
# 与其他 Morphism 组合
sequence = init @ bb @ final

# 编译和执行
from oasm.rtmq2.intf import sim_intf
from oasm.rtmq2 import assembler
from oasm.dev.main import run_cfg
from oasm.dev.rwg import C_RWG

intf = sim_intf()
intf.nod_adr = 0
intf.loc_chn = 1
run_all = run_cfg(intf, [0])
asm_seq = assembler(run_all, [('rwg0', C_RWG)])

from catseq.compilation import compile_to_oasm_calls, execute_oasm_calls

calls = compile_to_oasm_calls(sequence, asm_seq)
success, asm = execute_oasm_calls(calls, asm_seq, verbose=True)
```

## 常见用例

### 1. 性能关键代码
当 catseq 的抽象有性能开销时，直接用 OASM 优化。

### 2. 特殊硬件指令
使用 catseq 无法表达的复杂 OASM 指令序列。

### 3. 硬件循环
利用 OASM 的 `for_` 和 `end` 实现硬件级循环。

### 4. 精细时序控制
需要纳秒级精确控制的场景。

## 调试技巧

### 1. 查看生成的汇编

```python
success, asm = execute_oasm_calls(calls, asm_seq, verbose=True)
# verbose=True 会打印 RTMQ 汇编代码
```

### 2. 验证时长

```python
# 在 catseq 层面检查
print(f"Total duration: {morphism.total_duration_cycles} cycles")
print(f"             = {morphism.total_duration_cycles / 250:.2f} μs")
```

### 3. 状态检查

```python
# 检查每个通道的状态
for channel, lane in morphism.lanes.items():
    print(f"{channel.global_id}: {lane.operations[0].start_state} -> {lane.operations[-1].end_state}")
```

## 完整示例

参考 `examples/oasm_blackbox_complete_example.py` 获取更多示例：

- 简单 TTL 脉冲
- 带参数的可变脉冲
- 多通道位掩码控制
- 硬件循环实现
- 与普通 Morphism 组合

运行示例：

```bash
uv run python examples/oasm_blackbox_complete_example.py
```

## 总结

| 方面 | OASM 函数层 | catseq 包装层 |
|------|-------------|---------------|
| 内容 | 纯 OASM DSL | Channel, State, Board |
| 用途 | 实际硬件控制 | 状态管理和组合 |
| rwg 对象 | 自动注入 | 不可见 |
| 时长 | 手动计算 | 用于调度验证 |
| 状态 | 隐式 | 显式声明 |

**关键原则**：OASM 函数专注硬件，catseq 包装提供抽象和组合能力。
