# CatSeq 编译器设计详解

## 编译器总览

CatSeq 编译器将高层 Monoidal Category 抽象（Morphism）编译到底层 RTMQ 硬件指令（OASM）。采用**五阶段编译流程**（Plan 3 架构）。

```
Morphism → LogicalEvent → 成本分析 → 调度优化 → 约束验证 → OASMCall
```

## 五阶段编译流程

### Pass 1: 提取和翻译
**函数**: `_pass1_extract_and_translate()`

**输入**: `Morphism`  
**输出**: `Dict[OASMAddress, List[LogicalEvent]]`

**主要任务**:
1. **提取物理操作**: 调用 `merge_board_lanes()` 将 Morphism 转换为按板卡分组的 PhysicalLane
2. **过滤 IDENTITY**: 移除纯时间对齐的 IDENTITY 操作
3. **创建 LogicalEvent**: 为每个物理操作创建带时间戳的事件
4. **翻译为 OASM 调用**: 使用 pattern matching 将操作类型映射到 OASM 函数

**关键转换规则**:

| 操作类型 | OASM 函数 | 合并策略 |
|---------|----------|---------|
| TTL_INIT | ttl_config(mask, dir) | 同时刻合并为单个掩码 |
| TTL_ON/OFF | ttl_set(mask, state) | 同时刻合并为单个掩码 |
| RWG_INIT | rwg_init() | 板级操作，每板一次 |
| RWG_SET_CARRIER | rwg_set_carrier(ch, freq) | 1对1映射 |
| RWG_RF_SWITCH | rwg_rf_switch(mask, state) | 合并为掩码 |
| RWG_LOAD_COEFFS | rwg_load_waveform(params) | 每个波形一个调用 |
| RWG_UPDATE_PARAMS | rwg_play(pud_mask, iou_mask) | 合并为掩码 |
| SYNC_MASTER | trig_slave(PLACEHOLDER, code) | 使用占位符 |
| SYNC_SLAVE | wait_master(code) | 合并为单个调用 |

**占位符机制**:
- 使用 `WAIT_TIME_PLACEHOLDER = -999999` 标记需要后续计算的等待时间
- 在 Pass 5 替换为实际值

### Pass 2: 成本分析和 Epoch 检测
**函数**: `_pass2_cost_and_epoch_analysis()`

**主要任务**:
1. **OASM 成本估算**: 调用 `_estimate_oasm_cost()` 计算每个 OASM 调用的时钟周期成本
2. **Epoch 边界检测**: 识别全局同步操作（SYNC_MASTER/SYNC_SLAVE）
3. **复合时间戳分配**: 为每个事件分配 `(epoch, offset)` 时间戳

**成本估算逻辑**:
```python
def _estimate_oasm_cost(call: OASMCall, assembler_seq) -> int:
    if assembler_seq is None:
        return RTMQ_INSTRUCTION_COSTS.get(call.dsl_func, 10)
    
    # 使用 OASM assembler 生成实际汇编并计算指令数
    start = len(assembler_seq.asm.data)
    call.dsl_func(*call.args)
    end = len(assembler_seq.asm.data)
    return end - start
```

**Epoch 时间戳系统**:
- `epoch`: 同步点索引（从 0 开始）
- `offset`: 相对于 epoch 起点的时钟周期偏移
- 跨 epoch 边界时，时间戳重置为下一个 epoch 的偏移

### Pass 3: 调度和优化
**函数**: `_pass3_schedule_and_optimize()`

**主要任务**:
1. **识别流水线对**: 检测 RWG load-play 操作对
2. **计算最优调度**: 在满足 deadline 约束下，尽可能晚放置 load 操作
3. **更新时间戳**: 调整 load 操作的时间戳

**RWG 流水线约束**:
- `load` 操作必须在对应的 `play` 操作之前完成
- `load` 的 deadline = `play.timestamp - load.cost`
- 优化策略：尽可能晚加载，减少内存占用时间

**调度算法**:
```python
def _calculate_optimal_schedule(pair: PipelinePair) -> int:
    play_time = pair.play_start_time
    load_cost = pair.load_cost_cycles
    
    # 最晚可以开始 load 的时间
    latest_start = play_time - load_cost
    
    # 确保不早于原始时间
    return max(pair.load_event.timestamp_cycles, latest_start)
```

### Pass 4: 约束验证
**函数**: `_pass4_validate_constraints()`

**验证项**:

1. **黑盒函数独占性** (`_validate_black_box_exclusivity`)
   - 同一时刻同一板卡只能有一个黑盒函数
   
2. **RWG Load 串行约束** (`_validate_serial_load_constraints`)
   - 同一板卡的多个 load 操作必须串行执行
   
3. **Load Deadline 约束** (`_validate_load_deadlines`)
   - Load 操作必须在对应 play 操作之前完成
   
4. **跨 Epoch 时序一致性** (`_check_cross_epoch_violations_single_board`)
   - 验证编译后的时间戳与用户定义的时序一致

**错误示例**:
```python
# ❌ 同时刻两个黑盒函数
raise ValueError("Cannot execute two different black-box functions...")

# ❌ Load deadline 违反
raise ValueError(f"Load deadline violation: load finishes at {load_end}, play starts at {play_start}")
```

### Pass 5: 最终代码生成
**函数**: `_pass5_generate_final_calls()`

**主要任务**:
1. **替换占位符**: 调用 `_replace_wait_time_placeholders()` 计算并填充实际等待时间
2. **生成 OASM 序列**: 调用 `_pass4_generate_oasm_calls()` 将事件列表转换为 OASMCall 列表
3. **插入等待指令**: 在操作之间插入 `wait_mu(cycles)` 调用

**等待时间计算**:
```python
# 计算主机需要等待的时间
master_wait_time = max_slave_timestamp + 从机同步成本 + 网络延迟
```

**最终输出格式**:
```python
Dict[OASMAddress, List[OASMCall]]

# 示例
{
    OASMAddress.RWG0: [
        OASMCall(OASMFunction.TTL_CONFIG, (0x01, 0x00)),
        OASMCall(OASMFunction.WAIT_MU, (2500,)),
        OASMCall(OASMFunction.TTL_SET, (0x01, 0x01, "rwg")),
        ...
    ],
    OASMAddress.MAIN: [...]
}
```

## 关键数据结构

### LogicalEvent
```python
@dataclass
class LogicalEvent:
    timestamp_cycles: int          # 原始时间戳
    operation: AtomicMorphism      # 对应的原子操作
    is_critical: bool              # 是否为时序关键操作
    oasm_calls: List[OASMCall]     # 生成的 OASM 调用
    
    # 编译器填充的字段
    cost_cycles: int = 0           # OASM 成本
    epoch_id: int = 0              # Epoch 索引
    offset_cycles: int = 0         # Epoch 内偏移
```

### OASMCall
```python
@dataclass
class OASMCall:
    adr: OASMAddress               # 目标板卡地址
    dsl_func: OASMFunction         # OASM DSL 函数
    args: tuple                    # 函数参数
```

### PipelinePair
```python
@dataclass
class PipelinePair:
    load_event: LogicalEvent
    play_event: LogicalEvent
    
    @property
    def load_cost_cycles(self) -> int
    
    @property
    def play_start_time(self) -> int
```

## 编译优化

### 操作合并
同一时刻的同类型操作会被合并为单个 OASM 调用：
```python
# 用户代码
ttl_on(ch0) | ttl_on(ch1)

# 合并后的 OASM
ttl_set(mask=0x03, state=0x03)  # 一条指令控制两个通道
```

### 短延迟优化
```python
if cycles <= 4:
    nop(cycles)  # 使用 NOP 指令
else:
    wait(cycles)  # 使用 Timer 机制
```

### RWG Load 调度优化
将 load 操作尽可能晚调度，减少 SBG 参数在内存中的占用时间。

## 错误处理

### 编译时错误
- 状态不匹配
- 通道冲突
- 时序约束违反
- 硬件资源冲突

### 运行时错误（OASM 执行）
- 硬件初始化失败
- 通信超时
- 参数越界

## 调试支持

### Verbose 模式
```python
compile_to_oasm_calls(morphism, verbose=True)
```

输出每个编译阶段的详细信息。

### 内部事件返回
```python
# 测试用途
events = compile_to_oasm_calls(morphism, _return_internal_events=True)
```

返回内部 LogicalEvent 列表而非最终 OASMCall。

## 与硬件的映射

### RTMQ 指令成本（近似值）
```python
RTMQ_INSTRUCTION_COSTS = {
    OASMFunction.TTL_CONFIG: 2,
    OASMFunction.TTL_SET: 1,
    OASMFunction.WAIT_MU: lambda cycles: 4 if cycles <= 4 else 5,
    OASMFunction.RWG_INIT: 10,
    OASMFunction.RWG_SET_CARRIER: 5,
    ...
}
```

### OASM DSL 到 RTMQ 汇编
```python
# TTL 设置
ttl_set(mask=0x01, state=0x01)
# →
AMK - TTL 1.0 $01

# 等待
wait_mu(10000)
# →
CHI - TIM 0x000_00000
CLO - TIM 0x000_0270F
AMK - EXC 2.0 $01
AMK - RSM 1.1 $01
NOP H
```

## 未来扩展

- **更智能的调度算法**: 支持更复杂的资源分配
- **多板卡全局优化**: 跨板卡的指令重排
- **更精确的成本模型**: 考虑流水线和缓存效应
- **LLVM 后端**: 支持更高级的优化
