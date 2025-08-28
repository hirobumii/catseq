# CatSeq框架重新设计文档

## 设计哲学

CatSeq基于**范畴论（Category Theory）**的单子范畴（Monoidal Category）结构，通过数学严格性确保量子物理实验的安全性：**代码安全保证实验安全**。

### 核心原则
1. **验证过的单个时序模块（Morphism）组合后仍然安全**
2. **编译时类型检查 + 运行时物理约束验证**
3. **硬件抽象与实验逻辑分离**
4. **⚠️ 行为一致性原则：系统行为必须与用户定义完全一致**

### 行为一致性原则（关键设计约束）

**核心要求**：用户定义什么，系统就执行什么
- ✅ 用户写`ttl.pulse(duration=100e-6)`，系统必须产生exactly 100μs脉冲
- ✅ 用户写`morphismA | morphismB`，系统行为必须符合并行组合的数学定义
- ❌ **禁止擅自修改**用户指定的时长、状态或参数
- ❌ **禁止"聪明"的优化**可能导致与预期行为不一致

**允许的操作**：
- ✅ **纯数学变换**：应用分配律等数学等价变换（不改变执行结果）
- ✅ **验证与检测**：检查硬件约束违背，但不自动"修复"
- ✅ **分析与报告**：提供时序分析等信息，但不修改morphism

**禁止的操作**：
- ❌ **参数修改**：duration adjustment, lane balancing等时序优化
- ❌ **资源重分配**：SBG分配、通道映射等（这些在Channel创建时就固定）
- ❌ **行为优化**：任何改变用户预期行为的自动修改

**设计哲学**：**可预测性 > 性能优化**
- 实验物理学需要精确可控的行为
- 用户必须能够完全信任系统按定义执行
- 框架提供精确的数学语义，而非"智能"优化

## 数学基础：Monoidal Category

### Objects（对象）
**定义**：系统在某个时刻的完整状态
```python
@dataclass(frozen=True)
class SystemState:
    """系统完整状态 = 所有相关通道的状态快照"""
    channel_states: dict[Channel, State]
    timestamp: float
```

### Morphisms（态射）
**定义**：经过验证的时序演化过程
```python
@dataclass(frozen=True) 
class Morphism:
    dom: SystemState      # 定义域（起始状态）
    cod: SystemState      # 值域（结束状态）  
    duration: float       # 时序长度
    
    @abstractmethod
    def validate_physics(self) -> None:
        """验证物理可实现性"""
        ...
```

### 组合律

#### 1. 串行组合（@）：时序连接
```python
morphism1: A -> B  (时长 t1)
morphism2: B -> C  (时长 t2)
composed = morphism1 @ morphism2: A -> C  (时长 t1+t2)
```

**安全约束**：
- **状态匹配**：`morphism1.cod == morphism2.dom`
- **硬件验证**：每个通道的状态转换满足物理约束

#### 2. 并行组合（|）：同步执行
```python
morphismA: StateA1 -> StateA2  (时长 tA)
morphismB: StateB1 -> StateB2  (时长 tB)
parallel = morphismA | morphismB  (时长 max(tA, tB))
```

**时长同步**：自动插入`IdentityMorphism`补齐短的morphism

#### 3. 分配律：混合组合的标准化
```python
(A1|B1) @ (A2|B2) => (A1@Identity@A2) | (B1@B2@Identity)
```

**标准形式**：`(Lane1_morphisms) | (Lane2_morphisms) | ...`
- 每个lane是串行morphism序列：`M1 @ M2 @ M3 @ ...`

## 系统架构

### Layer 0: 基础协议 (`protocols.py`)
```python
class State(Protocol):
    """硬件状态基类"""
    pass

class Channel:
    """通道标识符（单例模式）"""
    name: str
    device: HardwareDevice

class HardwareDevice(Protocol):
    """硬件设备接口"""
    def validate_transition(self, from_state: State, to_state: State) -> None: ...
    def validate_taylor_coefficients(self, freq_coeffs, amp_coeffs) -> None: ...
```

### Layer 1: 状态定义 (`states/`)
```python
# TTL状态
class TTLState(State): pass
class TTLOn(TTLState): pass
class TTLOff(TTLState): pass

# RWG状态  
@dataclass(frozen=True)
class RWGState(State):
    sbg_id: int
    carrier_freq: float  
    freq: float          
    amp: float           
    phase: float         
    rf_enabled: bool     
```

### Layer 2: 硬件设备 (`hardware/`)
```python
class RWGDevice:
    def __init__(self, 
                 available_sbgs: set[int],
                 max_ramping_order: int,
                 amp_constraints: dict):
        self.available_sbgs = available_sbgs
        self.max_ramping_order = max_ramping_order
        self.amp_constraints = amp_constraints  # 如锁频约束
    
    def validate_taylor_coefficients(self, freq_coeffs, amp_coeffs):
        """验证Taylor系数的物理可实现性"""
        # 检查系数是否在硬件精度范围内
        # 检查特殊约束（如锁频通道振幅恒定）
        
class LockedRWGDevice(RWGDevice):
    """锁频RWG设备：振幅锁定，频率可扫描"""
    def validate_taylor_coefficients(self, freq_coeffs, amp_coeffs):
        super().validate_taylor_coefficients(freq_coeffs, amp_coeffs)
        A0, A1, A2, A3 = amp_coeffs
        if self.is_initialized and (A1 != 0 or A2 != 0 or A3 != 0):
            raise PhysicsViolationError("Locked RWG amplitude must remain constant")
```

### Layer 3: 简化的Morphism系统 (`morphisms/`)

基于设计简化原则，**统一使用单一Morphism类型**：

```python
@dataclass(frozen=True)
class Morphism:
    """统一的Morphism类型 - 所有操作最终都是多通道的"""
    dom: SystemState      # 起始状态
    cod: SystemState      # 结束状态  
    duration: float       # 总时长
    lanes: dict[Channel, list[AtomicOperation]]  # 标准形式存储
    
    def __matmul__(self, other: 'Morphism') -> 'Morphism':
        """@ 串行组合"""
        # 状态匹配验证 + 硬件转换验证
        
    def __or__(self, other: 'Morphism') -> 'Morphism':
        """| 并行组合"""
        # 时长同步 + Identity插入 + 分配律应用

@dataclass(frozen=True)
class AtomicOperation:
    """原子操作：对应一个硬件waveform segment"""
    channel: Channel
    from_state: State
    to_state: State
    duration: float          # 波形播放时长
    hardware_params: dict    # Taylor系数等硬件参数
    
    def get_write_instruction_count(self) -> int:
        """返回参数写入需要的指令数量"""
        # 用于编译器时序调度
```

### 原子操作类型（基于硬件约束）

基于RWG硬件的Taylor级数近似，原子操作类型由**多项式阶数**决定：

```python
# RWG原子操作
class HoldOperation(AtomicOperation):
    """静态保持：F1=F2=F3=0, A1=A2=A3=0"""
    
class LinearRampOperation(AtomicOperation):
    """线性变化：F2=F3=0 或 A2=A3=0"""
    
class QuadraticRampOperation(AtomicOperation):
    """二次变化：F3=0 或 A3=0"""
    
class CubicRampOperation(AtomicOperation):
    """三次变化：完整Taylor级数"""

# TTL原子操作
class TTLHoldOperation(AtomicOperation):
    """TTL状态保持"""
    
class TTLSwitchOperation(AtomicOperation):
    """TTL瞬间切换（零时长）"""
    duration: float = 0
```

### Layer 4: 工厂函数 (`morphisms/factories/`)

**用户接口**：通过工厂函数创建Morphism，内部自动分解为原子操作

```python
def ttl_pulse(channel: Channel, duration: float) -> Morphism:
    """TTL脉冲：分解为3个原子操作"""
    return Morphism(lanes={
        channel: [
            TTLSwitchOperation(channel, TTLOff(), TTLOn(), 0),      # 瞬间开启
            TTLHoldOperation(channel, TTLOn(), TTLOn(), duration),  # 保持duration  
            TTLSwitchOperation(channel, TTLOn(), TTLOff(), 0)       # 瞬间关闭
        ]
    })

def rwg_linear_sweep(channel: Channel, start_freq: float, end_freq: float, duration: float) -> Morphism:
    """RWG线性扫频：1个原子操作"""
    freq_coeffs = (start_freq, (end_freq-start_freq)/duration, 0, 0)
    amp_coeffs = (channel.current_amp, 0, 0, 0)  # 振幅恒定
    
    return Morphism(lanes={
        channel: [
            LinearRampOperation(
                channel=channel,
                from_state=RWGState(freq=start_freq, amp=channel.current_amp, ...),
                to_state=RWGState(freq=end_freq, amp=channel.current_amp, ...),
                duration=duration,
                hardware_params={'freq_coeffs': freq_coeffs, 'amp_coeffs': amp_coeffs}
            )
        ]
    })

def identity(channel: Channel, duration: float) -> Morphism:
    """恒等变换：用于时长补齐"""
    current_state = channel.get_current_state()
    return Morphism(lanes={
        channel: [
            HoldOperation(channel, current_state, current_state, duration)
        ]
    })
```

## 安全验证机制

### 1. Morphism构造时验证
```python
def create_linear_sweep(channel: Channel, start_freq: float, end_freq: float, duration: float):
    # 计算Taylor系数
    freq_coeffs = (start_freq, (end_freq-start_freq)/duration, 0, 0)
    amp_coeffs = (channel.current_amp, 0, 0, 0)  # 振幅恒定
    
    # 硬件验证
    channel.device.validate_taylor_coefficients(freq_coeffs, amp_coeffs)
    
    return LinearFreqSweepMorphism(...)
```

### 2. 组合时验证  
```python
def compose_serial(m1: Morphism, m2: Morphism):
    # 状态匹配检查
    if m1.cod != m2.dom:
        raise CompositionError("State mismatch in serial composition")
    
    # 每个通道的转换验证
    for channel in m1.channels | m2.channels:
        end_state = m1.get_final_state(channel) 
        start_state = m2.get_initial_state(channel)
        channel.device.validate_transition(end_state, start_state)
```

### 3. 特殊约束验证
```python
# 锁频通道示例
laser_lock = Channel("laser_lock", LockedRWGDevice(lock_amp=0.5))

# ✓ 允许：频率扫描，振幅恒定
freq_sweep = LinearFreqSweepMorphism(laser_lock, 100, 200, 10e-3)

# ✗ 禁止：振幅变化
amp_ramp = LinearAmpRampMorphism(laser_lock, 0.5, 0.8, 5e-3)  # 抛出异常

# ✗ 禁止：关闭RF
disable = DisableMorphism(laser_lock)  # 抛出异常
```

## 编译器系统

### 逻辑表示 vs 物理执行

**关键理解**：Morphism表达用户逻辑（波形播放时序），编译器负责物理实现（参数写入调度）

```python
# 用户视角：只关心波形播放的时序
ramp1 = rwg_sweep(rwg0, 100, 200, 10e-3)    # 10ms扫频
ramp2 = rwg_sweep(rwg0, 200, 300, 5e-3)     # 5ms扫频  
sequence = ramp1 @ ramp2                     # 15ms总时长，无缝连接
```

### 物理执行的两阶段过程

每个原子操作的物理执行分为两个阶段：

1. **参数写入阶段**：写入Taylor系数到硬件寄存器
2. **波形播放阶段**：触发硬件播放预设波形

**关键约束**：参数写入必须在波形播放开始前完成，且对用户透明

### 精确时序调度算法

```python
class RTMQCompiler:
    def __init__(self, clock_frequency: float):
        self.clock_period = 1.0 / clock_frequency
    
    def compile_sequence(self, operations: list[AtomicOperation]) -> list[RTMQInstruction]:
        """编译原子操作序列为RTMQ指令"""
        instructions = []
        
        for i, op in enumerate(operations):
            if i == 0:
                # 第一个操作：先写参数，再播放
                instructions.extend([
                    *self.generate_write_instructions(op),
                    TriggerPlayback(op.channel)
                ])
            else:
                # 后续操作：精确时序调度
                prev_op = operations[i-1]
                write_cycles = op.get_write_instruction_count()
                playback_cycles = self.duration_to_cycles(prev_op.duration)
                
                # 关键计算：剩余等待时间
                timer_cycles = playback_cycles - write_cycles
                
                if timer_cycles < 0:
                    raise CompilerError(
                        f"Previous waveform ({playback_cycles} cycles) "
                        f"shorter than write time ({write_cycles} cycles)"
                    )
                
                instructions.extend([
                    *self.generate_write_instructions(op),     # 立即写参数
                    TimerWait(timer_cycles * self.clock_period), # 等待剩余时间
                    TriggerPlayback(op.channel)                # 精确触发播放
                ])
        
        return instructions
```

### 指令时间模型

**基本原则**：参数写入时间 = 汇编指令数量 × 时钟周期

```python
class RTMQInstruction:
    cycles: int = 1  # 默认1个时钟周期

class TimerWait(RTMQInstruction):
    def __init__(self, duration: float):
        self.duration = duration
        self.cycles = duration_to_cycles(duration)  # 按实际等待时间

def calculate_write_cost(op: AtomicOperation) -> int:
    """计算参数写入的时钟周期数"""
    if isinstance(op, RWGOperation):
        # RWG参数写入：9个寄存器 = 9个时钟周期
        return 9
    elif isinstance(op, TTLOperation):
        # TTL参数写入：1个寄存器 = 1个时钟周期
        return 1
    else:
        return 0
```

### 编译示例

```python
# 用户代码
ramp1 = rwg_sweep(rwg0, 100, 200, 10e-3)    # 10ms播放
ramp2 = rwg_sweep(rwg0, 200, 300, 2e-3)     # 2ms播放  
sequence = ramp1 @ ramp2

# 编译器生成（假设写入需要3ms）：
instructions = [
    # t=0之前：写入ramp1参数（3ms）
    WriteRegister('FT0', 100),     # F0
    WriteRegister('FT1', 10),      # F1  
    WriteRegister('FT2', 0),       # F2
    WriteRegister('FT3', 0),       # F3
    WriteRegister('AP0', 0.5),     # A0
    WriteRegister('AP1', 0),       # A1
    WriteRegister('AP2', 0),       # A2
    WriteRegister('AP3', 0),       # A3
    WriteRegister('POF', 0),       # Phase
    
    # t=0ms: 触发ramp1播放（1个周期）
    TriggerPlayback('rwg0'),
    
    # t=0ms: 立即写入ramp2参数（3ms）
    WriteRegister('FT0', 200),     # 与ramp1播放并行
    WriteRegister('FT1', 20),      
    WriteRegister('FT2', 0),       
    WriteRegister('FT3', 0),       
    WriteRegister('AP0', 0.5),     
    WriteRegister('AP1', 0),       
    WriteRegister('AP2', 0),       
    WriteRegister('AP3', 0),       
    WriteRegister('POF', 0),
    
    # t=3ms: 等待剩余时间（7ms = 10ms - 3ms）
    TimerWait(7e-3),
    
    # t=10ms: 触发ramp2播放（1个周期）
    TriggerPlayback('rwg0')
    
    # t=12ms: 序列结束
]
```

### 编译器错误检测

```python
# 错误场景：波形时间过短
short_pulse = rwg_sweep(rwg0, 100, 200, 1e-3)   # 1ms播放
next_sweep = rwg_sweep(rwg0, 200, 300, 5e-3)    # 需要3ms写入时间

sequence = short_pulse @ next_sweep  
# 编译器错误：1ms < 3ms，无法完成参数写入
```

## 类型安全

```python
# 编译时类型检查
TTLChannel = Channel[TTLState]
RWGChannel = Channel[RWGState] 

def ttl_pulse(channel: TTLChannel, duration: float) -> TTLPulseMorphism: ...
def rwg_sweep(channel: RWGChannel, start_freq: float, end_freq: float, duration: float) -> LinearFreqSweepMorphism: ...

# IDE自动补全和错误检查
ttl0 = TTLChannel("ttl0", TTLDevice())
rwg0 = RWGChannel("rwg0", RWGDevice(...))

pulse = ttl_pulse(ttl0, 1e-6)  # ✓ 类型匹配
sweep = rwg_sweep(rwg0, 100, 200, 10e-3)  # ✓ 类型匹配 
wrong = ttl_pulse(rwg0, 1e-6)  # ✗ 编译时类型错误
```

## 总结

### 设计架构的核心优势

CatSeq通过严格的数学框架和精确的物理建模，实现了：

1. **数学严格性**：基于范畴论的Monoidal Category结构，确保组合安全
2. **物理约束建模**：精确反映硬件的Taylor级数限制和时序约束
3. **编译时类型安全**：IDE自动补全和错误检查，减少运行时错误
4. **运行时物理验证**：多层验证机制防止硬件约束违反
5. **精确时序控制**：编译器智能调度参数写入，确保无缝时序连接
6. **设计简化**：统一Morphism类型，用户友好的工厂函数接口
7. **实验安全保障**：代码安全直接保证实验安全，防止硬件损坏和实验失败

### 关键创新点

1. **逻辑-物理分离**：用户只需关心波形播放逻辑，编译器处理底层时序调度
2. **原子操作抽象**：基于硬件segment的原子操作设计，直接对应物理实现  
3. **智能时序调度**：编译器自动计算参数写入时间，优化指令序列
4. **特殊约束支持**：支持锁频等特殊物理约束，确保关键实验条件
5. **组合律实现**：自动应用分配律和Identity插入，简化复杂时序组合

### 实际价值

- **提高实验可靠性**：数学验证确保实验序列的物理正确性
- **降低开发门槛**：类型安全和IDE支持提高开发效率
- **支持复杂实验**：无缝支持多通道并行和复杂时序组合
- **硬件抽象**：统一接口支持不同硬件类型和约束
- **错误预防**：编译时检查大幅减少运行时错误和硬件风险

---

## Future Evolution and Roadmap

### CatSeq框架改进与演进计划

**目标**：将CatSeq从一个具有坚实理论基础的核心框架，演进为一个**可扩展、高容错、表达力强且开发者友好**的工业级量子实验设计与控制平台。本计划旨在解决当前设计中的潜在瓶颈，并为未来功能扩展铺平道路。

---

### 路线图总览

本计划分为三个阶段，遵循“**稳固核心 -> 完善工具链 -> 扩展能力**”的演进路径。

* **阶段一：核心模型重构 (Foundational Enhancements)**
    * **目标**：解决状态管理的刚性和可扩展性问题，提升框架的灵活性和性能。
    * **关键成果**：引入部分状态管理，解耦通道依赖，实现确定性的序列构建。

* **阶段二：编译器与开发者体验优化 (Compiler & Tooling Maturity)**
    * **目标**：提升编译器的物理真实性和可靠性，并为开发者提供强大的调试工具。
    * **关键成果**：资源感知的编译器、高保真错误报告、序列可视化工具。

* **阶段三：高级功能与表达力扩展 (Advanced Capabilities & Expressiveness)**
    * **目标**：支持更复杂的实验逻辑，赋能用户构建可复用的高级时序库。
    * **关键成果**：动态控制流原型、参数化子序列（宏）功能。

---

### 阶段一：核心模型重构 (Foundational Enhancements)

#### 1.1. 实施部分状态（Partial State）管理模型
* **问题**：当前的`SystemState`是全局的，导致通道间不必要的耦合，且在大规模系统中存在性能瓶颈。
* **行动计划**：
    1.  **修改`Morphism`定义**：`dom`和`cod`中的`channel_states`仅需包含该`Morphism`直接影响的通道。
    2.  **重构组合逻辑 (`@`)**：
        * 验证时，仅对两个`Morphism`共同涉及的通道进行`cod`与`dom`的匹配检查。
        * 组合后的新`Morphism`的状态，通过合并两个`Morphism`的状态来计算。对于只在`m1`中出现、未在`m2`中改变的通道，其状态从`m1`的`cod`继承。
    3.  **更新并行逻辑 (`|`)**：合并`lanes`时，`dom`和`cod`也进行相应的合并，而不是填充所有通道的`IdentityMorphism`。

#### 1.2. 引入显式的序列构建器 (SequenceBuilder)
* **问题**：依赖隐式的全局`channel.get_current_state()`使序列构建过程不确定，不利于代码复用和测试。
* **行动计划**：
    1.  **创建`SequenceBuilder`类**：
        ```python
        class SequenceBuilder:
            def __init__(self, initial_state: SystemState):
                # ...

            def append(self, morphism: Morphism) -> None:
                # 在内部进行状态匹配和演化
                # ...

            def build(self) -> Morphism:
                # 返回最终组合好的、经过完全验证的Morphism
                # ...
        ```
    2.  **废弃隐式状态查询**：移除`channel.get_current_state()`方法，强制所有序列都在`SequenceBuilder`的上下文中构建。
    3.  **更新用户工作流**：
        * **之前 (隐式)**: `seq = ttl_pulse(...) @ identity(rwg0, ...)`
        * **之后 (显式)**:
            ```python
            # 定义初始条件
            initial_state = SystemState(channel_states={...})

            # 建立序列
            builder = SequenceBuilder(initial_state)
            builder.append(ttl_pulse(ttl0, 1e-6))
            builder.append(rwg_sweep(rwg0, 100, 200, 10e-3))

            # 生成最终序列
            final_sequence = builder.build()
            ```
        此举可确保序列的构建是**确定性**和**可移植**的。

---

### 阶段二：编译器与开发者体验优化 (Compiler & Tooling Maturity)

#### 2.1. 实现资源感知的编译器调度器
* **问题**：编译器的时间模型未考虑硬件总线竞争等共享资源冲突。
* **行动计划**：
    1.  **定义资源模型**：在硬件定义层 (`HardwareDevice`) 中声明其使用的共享资源（如`bus='FPGA_BUS_1'`）。
    2.  **增强编译器**：`RTMQCompiler`在调度`generate_write_instructions`时，必须检查目标资源是否被占用。
    3.  **冲突处理**：如果检测到总线冲突，编译器应采取策略，如自动插入等待指令 (`NOP`) 来序列化写入操作，并重新计算时序。如果无法在给定时间内解决冲突，则抛出详细的`CompilerResourceError`。

#### 2.2. 开发高保真错误报告系统
* **问题**：`CompositionError`等通用异常信息不足以帮助用户快速定位代码错误。
* **行动计划**：
    1.  **追踪元数据**：在`Morphism`创建时，记录其来源（如工厂函数名和参数）。
    2.  **提供上下文**：当组合失败时，错误信息应包含：
        * 哪两个高层操作 (`Morphism`) 无法组合。
        * 具体是哪个`Channel`的状态不匹配。
        * 期望的状态 (`expected`) 和实际遇到的状态 (`got`)。
        * **示例**：`CompositionError: Failed to compose 'rwg_sweep(rwg0, ...)' after 'hold(rwg0, ...)'. Reason: State mismatch on channel 'rwg0'. Expected initial frequency 200.0 MHz, but got 150.0 MHz.`

#### 2.3. 构建序列可视化与调试工具
* **问题**：复杂的`Morphism`对象内部结构不透明，难以调试。
* **行动计划**：
    1.  **实现`__repr__`和`_repr_html_`**：为`Morphism`提供丰富的文本和（在Jupyter中）HTML表示，清晰地展示每个`lane`的时序和总时长。
    2.  **开发`.visualize()`方法**：生成一个ASCII或图形化的时序图，直观展示多通道的并行与串行关系。
        ```
        Channel | 0ms      5ms      10ms     15ms
        --------|----------|--------|--------|------>
        ttl0    |--PULSE---|--HOLD--|
        rwg0    |--HOLD----|--SWEEP----------|
        ```

---

### 阶段三：高级功能与表达力扩展 (Advanced Capabilities & Expressiveness)

#### 3.1. 设计参数化子序列（宏）功能
* **问题**：缺乏官方支持来创建和复用带有参数的复杂子序列。
* **行动计划**：
    1.  **推广工厂函数模式**：鼓励用户编写返回`Morphism`的函数。
    2.  **支持函数式组合**：确保可以自然地将这些函数组合起来。
        ```python
        def ramsey_sequence(channel, freq_detuning, pulse_time, wait_time) -> Morphism:
            pi_half_pulse = rwg_pulse(channel, duration=pulse_time, freq_offset=0)
            wait = identity(channel, duration=wait_time)
            # 假设detuning通过phase实现
            final_pi_half = rwg_pulse(channel, duration=pulse_time, phase_offset=freq_detuning*wait_time)

            return pi_half_pulse @ wait @ final_pi_half

        # 使用
        exp_seq = ramsey_sequence(rwg1, 1e6, 1e-7, 5e-6)
        ```

#### 3.2. 探索动态控制流的原型设计
* **问题**：框架目前仅支持静态序列，无法响应实验过程中的实时反馈。
* **行动计划（研究性）**：
    1.  **定义`BranchMorphism`**：这是一个特殊的`Morphism`，它包含多个可能的执行路径和一个外部触发条件。
    2.  **编译器支持**：编译器需要能将这种`BranchMorphism`编译为特定的硬件指令，如“跳转-如果-触发器A为高”。
    3.  **硬件抽象**：在`HardwareDevice`协议中添加与实时触发和条件执行相关的接口。
    4.  **目标**：首先实现一个简单的`if/else`结构，例如，根据一个TTL输入信号的值，在两个预编译的`AtomicOperation`序列之间进行选择。