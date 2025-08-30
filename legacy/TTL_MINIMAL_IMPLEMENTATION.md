# TTL 最小实现：从 Monoidal Category 到 OASM DSL

## 目标
实现一个最小但完整的 TTL 控制系统，从 Monoidal Category 数学抽象到实际可运行的 OASM DSL 代码。

## 核心概念

### RTMQ 平台
- **RTMQ**: 我们的目标硬件平台，专为量子实验控制设计
- **OASM**: 对 RTMQ 汇编的 Python DSL 抽象
- **时钟**: 250 MHz (`us = 250`)

### OASM TTL Pulse 示例
```python
rwg.ttl.on(1)              # 打开 TTL 通道 1
rwg.timer(10000,wait=False) # 等待 10000 个时钟周期，不阻塞
rwg.hold()                 # 暂停等待 timer 完成
rwg.ttl.off(1)             # 关闭 TTL 通道 1
```

### 关键观察
1. **设备对象**: `rwg` - 表示 RWG 设备实例
2. **TTL 控制**: `rwg.ttl.on(ch)` / `rwg.ttl.off(ch)` - 通道级别控制
3. **时序控制**: `rwg.timer(cycles, wait=False)` - 精确时钟周期计时
4. **同步机制**: `rwg.hold()` - 等待操作完成

### 对应的 RTMQ 汇编
```asm
AMK - TTL 2.0 $01          # TTL ON: 设置 TTL 位字段，$01 = 0x01 (通道 0)
CHI - TIM 0x000_00000      # Timer 高位 = 0
CLO - TIM 0x000_0270F      # Timer 低位 = 0x270F = 10000 (dec)
AMK - EXC 2.0 $01          # 异常控制：启用恢复
AMK - RSM 1.1 $01          # 恢复控制：启用 timer 恢复
NOP H                      # 暂停等待恢复信号
AMK - TTL 2.0 $00          # TTL OFF: 清除 TTL 位字段
```

### 重要发现
1. **时间计算**: `10000` 个时钟周期 = 10000 / 250MHz = **40μs**
2. **通道映射**: Python 中的通道 1 对应汇编中的位 0 (`$01` = 0x01)
3. **Timer 机制**: 
   - 使用 `CHI`/`CLO` 设置 32位 timer 值
   - `EXC` 和 `RSM` 配合实现异步等待
   - `NOP H` 暂停直到 timer 触发恢复
4. **位操作**: `AMK - TTL 2.0` 使用位字段操作控制 TTL 状态

## Morphism 抽象设计

### 原子 Morphism 分解
基于 OASM TTL pulse 示例，我们将其分解为三个原子 Morphism：

1. **`ttl_on` Morphism**: `rwg.ttl.on(1)` - 设置 TTL 通道状态
2. **`wait` Morphism**: `rwg.timer() + rwg.hold()` - 时间等待操作  
3. **`ttl_off` Morphism**: `rwg.ttl.off(1)` - 清除 TTL 通道状态

### 编译器职责分工
- **用户层**: 只负责 Morphism 的 tensor product (并行组合)
- **编译器层**: 负责底层 OASM 代码的自动调整和优化

### 设计原则：编译时智能调度
当发生并行操作时，例如：
```python
pulse1 = ttl_on(1) @ wait(40us) @ ttl_off(1)  # 通道 1 脉冲
pulse2 = ttl_on(2) @ wait(20us) @ ttl_off(2)  # 通道 2 脉冲
parallel = pulse1 | pulse2                    # 并行执行
```

编译器需要：
1. **自动重新调度** `rwg.timer()` 和 `rwg.hold()` 的时机
2. **合并时序控制**，避免冲突的 timer 设置
3. **优化同步点**，确保正确的并行执行
4. **对用户透明**，用户无需关心底层调度细节

这个设计将复杂的硬件时序调度从用户抽象中分离出来。

## 组合规则语义

### 串行组合 (@) 
**严格状态匹配**的时序连接：
```python
sequence = ttl_on(1) @ ttl_off(1)  # 严格要求 ON == ON 状态匹配
```
- 执行顺序：按顺序执行各个 Morphism
- **状态验证**：前一个 Morphism 的 end_state 必须等于后一个的 start_state
- 总时长：各个 Morphism 时长之和

### 自动匹配组合 (>>) 
**智能状态推导**的时序连接：
```python
sequence = ttl_init(1) >> wait(40e-6) >> ttl_on(1)  # 自动推导 wait 的状态
```
- 执行顺序：按顺序执行各个 Morphism
- **自动推导**：对于 `wait` Morphism，自动从前一个 Morphism 推导其 domain/codomain
- **状态适配**：智能处理状态转换，减少手动状态管理

### 并行组合 (|) - 张量积
同步执行，通过 Identity Morphism 对齐时间：
```python
pulse1 = ttl_on(1) @ wait(40us) @ ttl_off(1)  # 通道 1 操作
pulse2 = ttl_on(2) @ wait(20us) @ ttl_off(2)  # 通道 2 操作
parallel = pulse1 | pulse2                    # 合法：不同通道
```
- **Identity 补齐**: 较短的 Morphism 后拼接 Identity Morphism
- **同步执行**: 所有通道同时开始，同时结束

### 张量积约束
**关键约束**: 同一通道不能与自己做张量积
```python
ttl_on(1) | ttl_on(2)   # ✅ 合法 - 不同通道
ttl_on(1) | ttl_off(1)  # ❌ 不合法 - 同一通道张量积
```

这是 Monoidal Category 的基本要求：张量积必须在不相交的对象上进行。

### 时间单位系统
- **基准时钟**: 250 MHz (1个时钟周期 = 4ns)
- **内部存储**: 使用整数时钟周期，避免浮点误差
- **用户接口**: 接受微秒输入，自动转换为时钟周期
- **转换关系**: 1μs = 250个时钟周期

### 原子操作时间成本
- `ttl_init()`, `ttl_on()`, `ttl_off()`: 各消耗 **1个时钟周期** (4ns)
- `wait(duration_us)`: 消耗指定的时间（用户以微秒输入，内部转换为时钟周期）
- `identity(duration)`: 保持当前状态的等待操作

## Morphism 到 OASM 编译策略

### 并行操作的硬件合并
对于同一板卡的多通道 TTL 操作，编译器需要合并指令：

**示例**：
```python
pulse1 = ttl_on(1) @ wait(40us) @ ttl_off(1)
pulse2 = ttl_on(2) @ wait(20us) @ ttl_off(2)
parallel = pulse1 | pulse2
```

**编译策略**：
1. **合并同时操作**: `ttl_on(1) | ttl_on(2)` → 单条 `AMK - TTL 3.0 $03` (掩码 0x03 = 通道0+通道1)
2. **时序分析**: 识别关键时间点
   - t=0: 通道1,2同时开启  
   - t=20us: 通道2关闭
   - t=40us: 通道1关闭
3. **指令调度**: 扣除指令执行时间，精确计算 timer 值

### Identity Morphism 处理
- **概念**: Identity 表示"保持当前状态"
- **实现**: 无需生成额外 OASM 代码，仅在编译时提醒某通道保持状态
- **作用**: 用于时间对齐和状态追踪

### 精确时序计算
考虑指令执行开销：
- `AMK - TTL` 指令: 1个时钟周期
- Timer 设置 (`CHI`+`CLO`): 2个时钟周期  
- 实际 wait 时间 = 用户指定时间 - 指令开销

### OASM Port 能力分析
`rwg.ttl` port 提供以下方法：
- `ttl.on(channel)` - 开启指定通道
- `ttl.off(channel)` - 关闭指定通道  
- `ttl.set(value)` - 直接设置 TTL 寄存器值

**多通道支持评估**：
- 单个 `ttl.on()` 调用可能只支持单通道
- 多通道同时控制可能需要：
  1. 使用 `ttl.set(mask)` 直接设置位掩码
  2. 或生成底层汇编 `AMK - TTL 3.0 $03`

**下一步验证**：需要实际测试 OASM port 的多通道能力，如不满足需求则实现底层汇编生成。

## 编译器架构设计

### 1. 无中间表示的直接编译
- **原子 Morphism** 直接对应 OASM DSL 函数
- 不需要复杂的中间表示层
- 编译流程：`Morphism 组合 → 时间戳分析 → OASM 代码生成`

### 2. 基于机器时间戳的调度
每个 Morphism 内部记录：
- **开始时间戳** (start_time)
- **结束时间戳** (end_time)

**合并判断**：
- 时间戳相同 = 可以合并操作
- 仅限单个寄存器的读写操作（如 TTL 的 AMK 指令）

**调度原则**：
- **忠实实现用户时序**，不做"最优化"调度
- Identity Morphism 补齐基于时间戳差异

### 3. 优化策略限制
**允许的优化**：
- 短时间等待（几个时钟周期）使用 `NOP` 替代 timer
- 扁平化存储：`@` 组合以列表形式存储，避免嵌套结构

**禁止的优化**：
- 不重排用户定义的操作顺序
- 不修改用户指定的时序关系

### 4. 编译时错误检查
**张量积 (|) 检查**：
- 验证两个 Morphism 的通道无交集
- 报告通道冲突错误

**串行组合 (@) 行为**：
- **严格状态匹配**：前一个 Morphism 的结束状态必须与后一个的开始状态**完全相同**
- 合法示例：`ttl_on(1) @ ttl_off(1)` (OFF→ON @ ON→OFF)  
- 非法示例：`ttl_on(1) @ ttl_on(1)` (OFF→ON @ OFF→ON) - 状态不连续
- Morphism 层面强制状态连续性，确保逻辑清晰性

**硬件资源冲突**：
- 编译时检测和报告
- 例如：多个 Morphism 同时需要 timer 资源

## 层级化时间模型

### 两层抽象结构
1. **原子 Morphism** - 基本操作单元（`ttl_on`, `wait`, `ttl_off`）
2. **Lane** - 单通道上的操作序列（原子 Morphism 通过 `@` 串联）
3. **组合 Morphism** - 多个 Lane 的并行组合（通过 `|` 并联）

### 时间戳设计
**原子 Morphism**：
- 用户提供 `duration`
- 独立时：`start_time=0, end_time=duration`

**Lane**：  
- 整体 `start_time` = 第一个原子 Morphism 的 `start_time`
- 整体 `end_time` = 最后一个原子 Morphism 的 `end_time`
- 内部原子 Morphism 有相对于 Lane 的绝对时间戳

**并行组合**：
- `|` 操作对齐各 Lane 的 `start_time=0`
- 短 Lane 自动补齐 Identity Morphism 到最长时间

### 分配律应用
复杂组合需要重新组织结构：
```python
(A1 | B1) @ (A2 | B2)  # 原始表达式
# 重写为：
(A1 @ A2) | (B1 @ B2)  # 应用分配律，按通道重新组织
```

这确保了 `|` 始终作用于 Lane 级别，而不是混合层级。

### 函数式不可变性
- 所有组合操作创建新对象
- 原始 Morphism/Lane 保持不变
- 支持安全的并发和缓存

## 实现状态更新（2025年）

### 已完成的核心功能

#### 1. 板卡级别的硬件抽象
```python
@dataclass(frozen=True)
class Board:
    id: str  # "RWG_0", "RWG_1"

@dataclass(frozen=True)  
class Channel:
    board: Board      # 所属板卡
    local_id: int     # 板卡内通道号 (0-based)
    
    @property
    def global_id(self) -> str:
        return f"{self.board.id}_TTL_{self.local_id}"
```

**编译复杂度分析**：
- **不同板卡并行** (简单)：每个板卡独立编译，只需同步启动
- **同板卡并行** (复杂)：需要时序合并和TTL寄存器位掩码操作

#### 2. 完整的 Morphism 数据结构
```python
@dataclass(frozen=True)
class Morphism:
    lanes: Dict[Channel, Lane]  # Channel -> Lane 映射
```

**关键设计优势**：
- 清晰的通道分离：每个通道独立管理
- 高效的并行处理：`|` 操作就是字典合并  
- 简化编译：按通道生成 OASM 代码
- 自然的时间对齐：自动补齐 identity 操作

#### 3. PhysicalLane 合并算法
基于时间戳重新编排，只保留实际的硬件操作：
```python
def merge_board_lanes(board: Board, board_lanes: Dict[Channel, Lane]) -> PhysicalLane:
    # 收集所有 TTL 状态变化事件
    ttl_events: Dict[int, Dict[int, TTLState]] = {}  # timestamp -> {channel_local_id: target_state}
    
    # wait/identity 操作只是时间间隔，不生成物理操作
    # 只记录实际的 TTL 状态变化
```

**正确的时序编排示例**：
```
#1 t=0.0μs: ttl_set(mask=0x03[0,1]) ch0→OFF, ch1→OFF  // 同时初始化
#2 t=10.0μs: ttl_set(mask=0x01[0]) ch0→ON              // 通道0开启
#3 t=15.0μs: ttl_set(mask=0x02[1]) ch1→ON              // 通道1开启  
#4 t=40.0μs: ttl_set(mask=0x02[1]) ch1→OFF             // 通道1关闭
#5 t=50.0μs: ttl_set(mask=0x01[0]) ch0→OFF             // 通道0关闭
```

#### 4. 灵活的 `|` 操作符
支持所有组合类型：
- `AtomicMorphism | AtomicMorphism` → `Morphism`
- `AtomicMorphism | Morphism` → `Morphism`  
- `Morphism | AtomicMorphism` → `Morphism`
- `Morphism | Morphism` → `Morphism`

#### 5. 多层次可视化系统
```python
# 1. 紧凑视图 - 智能识别脉冲模式
⚡ rwg0[ch0:pulse(20.0μs),ch1:pulse(18.0μs)] | rwg1[ch0:pulse(14.0μs)] (20.0μs)

# 2. Lane 并排视图 - 隐藏硬件细节，用户友好
rwg0_TTL_0  │ init → wait(5.0μs) → ON → wait(15.0μs) → OFF
rwg0_TTL_1  │ init → wait(10.0μs) → ON → wait(8.0μs) → OFF → hold(2.0μs)
rwg1_TTL_0  │ init → wait(2.0μs) → ON → wait(12.0μs) → OFF → hold(6.0μs)

# 3. 详细描述 - 完整信息
# 4. 全局时间线 - 硬件调试
```

### 待实现功能

#### 1. Morphism @ Morphism 组合语义
根据分配律重新组织结构：
```python
# 输入：(A1(10μs) | B1(15μs)) @ (A2(15μs) | B2(5μs))
# 输出：(A1(10μs) @ wait(5μs) @ A2(15μs)) | (B1(15μs) @ B2(5μs) @ wait(10μs))
```

**实现策略**：
1. **时长分析**：计算两个 Morphism 的时长差异
2. **通道匹配**：按通道名称配对操作序列
3. **自动补齐**：较短序列自动插入 wait 或 identity 操作
4. **状态验证**：严格匹配模式下验证状态连续性

#### 2. 编译器接口设计
```python
def compile_to_oasm(morphism: Morphism) -> Dict[Board, str]:
    """将 Morphism 编译为每个板卡的 OASM 代码"""
    result = {}
    for board, board_lanes in morphism.lanes_by_board().items():
        physical_lane = merge_board_lanes(board, board_lanes)
        oasm_code = generate_oasm_for_board(physical_lane)
        result[board] = oasm_code
    return result
```

#### 3. 状态推导优化
当前的 `>>` 操作符已实现基本的状态推导，需要扩展到更复杂场景：
- 跨 Morphism 的状态推导
- 多通道状态一致性验证
- 错误恢复和建议

### 架构设计验证

当前实现完美体现了 Monoidal Category 的数学结构：
- **Objects**: 完整系统状态（Channel->State 映射）
- **Morphisms**: 物理过程（时间演化）
- **串行组合** (`@`): 严格的函数复合
- **并行组合** (`|`): 张量积，通道独立
- **Identity**: 自动时长补齐

**下一步优先级**：
1. 实现 `Morphism @ Morphism` 的分配律算法
2. 完善编译器接口和 OASM 代码生成
3. 添加更多测试用例和错误处理
