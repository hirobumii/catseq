# CatSeq 架构设计

## 整体架构图（v0.2.1 - xDSL 集成）

```
用户代码 (双层 API)
    ├─ Morphism API (Category Theory)
    └─ Program API (Functional Monad) 🆕
         ↓
    Program AST 🆕
         ↓
    xDSL IR (program dialect) 🆕
         ↓
    [未来] Pattern Rewriting & Optimization
         ↓
    编译器 (5 阶段)
         ↓
  OASM DSL 函数调用
         ↓
   RTMQ 汇编指令
         ↓
    硬件执行
```

**注**: 虚线框内为 v0.2.1 新增的 xDSL/MLIR 基础设施

## 层次抽象

### 1. 用户抽象层 - Morphism

**核心类型**:
- `Morphism`: 包含多个通道的 Lane 字典，表示完整的物理过程
- `AtomicMorphism`: 单个原子操作（TTL ON/OFF, RWG 操作等）
- `Lane`: 单通道上的原子操作序列

**组合操作符**:
- `@` (**严格串行组合**): 要求状态严格匹配
  - `ttl_on(ch1) @ ttl_off(ch1)` ✅ 合法
  - `ttl_on(ch1) @ ttl_on(ch1)` ❌ 状态不连续
  
- `>>` (**自动状态推导组合**): 智能推导状态
  - `ttl_init(ch1) >> wait(40e-6) >> ttl_on(ch1)` - 自动推导 wait 的状态
  
- `|` (**并行组合/张量积**): 不同通道并行执行
  - `ttl_on(ch1) | ttl_on(ch2)` ✅ 不同通道
  - `ttl_on(ch1) | ttl_off(ch1)` ❌ 同通道不能并行

**时间单位**:
- 内部存储: 整数时钟周期（避免浮点误差）
- 用户接口: 微秒（自动转换）
- 转换关系: 1μs = 250 个时钟周期

### 2. 中间表示 - Lane & PhysicalLane

**Lane** (逻辑层):
- 单通道上的原子操作序列
- 保持操作的逻辑顺序
- 包含 IDENTITY 操作用于时间对齐

**PhysicalLane** (物理层):
- 合并同板卡的多通道 Lane
- 只保留实际硬件操作（去除 IDENTITY）
- 基于时间戳重新编排

**关键函数**: `merge_board_lanes(board, board_lanes) -> PhysicalLane`

### 3. 编译器层 - 五阶段编译

#### Pass 1: 提取和翻译 (`_pass1_extract_and_translate`)
- 从 Morphism 提取物理操作
- 转换为 LogicalEvent 列表
- 生成 OASM 调用（带占位符）
- 合并同时发生的操作（TTL 位掩码）

#### Pass 2: 成本分析和 Epoch 检测 (`_pass2_cost_and_epoch_analysis`)
- 计算每个 OASM 调用的时钟周期成本
- 检测 Epoch 边界（全局同步点）
- 为每个事件分配 (epoch, offset) 复合时间戳

#### Pass 3: 调度和优化 (`_pass3_schedule_and_optimize`)
- 识别 RWG load-play 流水线对
- 计算最优调度时间
- 优化 load 操作的放置

#### Pass 4: 约束验证 (`_pass4_validate_constraints`)
- 验证黑盒函数独占性
- 验证 RWG load 串行约束
- 验证 load deadline 约束
- 检查跨 epoch 时序一致性

#### Pass 5: 最终代码生成 (`_pass5_generate_final_calls`)
- 替换等待时间占位符
- 生成最终 OASM 调用序列
- 按板卡分组输出

**输出**: `Dict[OASMAddress, List[OASMCall]]`

### 4. OASM DSL 层

**核心函数** (catseq/compilation/functions.py):
- `ttl_config(mask, dir)` - TTL 初始化
- `ttl_set(mask, state, board_type)` - TTL 状态设置
- `wait_mu(cycles)` - 精确时钟周期等待
- `wait_us(duration)` - 微秒等待
- `rwg_init()` - RWG 板卡初始化
- `rwg_set_carrier(chn, freq)` - 设置载波频率
- `rwg_rf_switch(ch_mask, state_mask)` - RF 开关控制
- `rwg_load_waveform(params)` - 加载波形参数
- `rwg_play(pud_mask, iou_mask)` - 触发波形播放

**OASM 底层调用** (来自 oasm.rtmq2 和 oasm.dev.rwg):
- `amk()` - AMK 指令（掩码操作）
- `sfs()` - SFS 指令（子文件选择）
- `wait()` - Timer 等待
- `nop()` - 空操作
- `send_trig_code()` / `wait_rtlk_trig()` - 同步触发

### 5. 硬件层 - RTMQ

**支持的硬件模块**:
- **Main**: GPIO 和系统协调
- **RWG**: RF 波形生成器（4 通道，1 GSps）
- **RSP**: 可重构信号处理器

**时序精度**: 4ns (250 MHz)

## 板卡和通道抽象

```python
@dataclass(frozen=True)
class Board:
    id: str  # "RWG_0", "RWG_1", "MAIN"

@dataclass(frozen=True)  
class Channel:
    board: Board
    local_id: int      # 板卡内通道号 (0-based)
    channel_type: ChannelType  # TTL, RWG, RSP
    
    @property
    def global_id(self) -> str:
        return f"{self.board.id}_{self.channel_type.name}_{self.local_id}"
```

## 状态机制

每个通道维护一个状态对象：
- `TTLState(value)` - TTL 高/低
- `RWGIdle()` - RWG 空闲
- `RWGActive(carrier_freq, rf_on, pending_waveforms)` - RWG 活跃

状态转换通过 Morphism 执行，编译器验证状态连续性。

## 编译时错误检查

- ✅ 张量积通道冲突检查
- ✅ 串行组合状态匹配检查
- ✅ 硬件资源冲突检查
- ✅ 时序约束验证
- ✅ 黑盒函数独占性检查

## 可视化系统

多层次时间线视图：
1. **紧凑视图** - 智能识别脉冲模式
2. **Lane 并排视图** - 隐藏硬件细节
3. **详细描述** - 完整操作信息
4. **全局时间线** - 硬件调试级别
