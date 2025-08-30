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

## OASM DSL 翻译系统

### Morphism 到 OASM 的翻译过程

从抽象的 Morphism 到具体的硬件控制需要经过**三层翻译**：

```
Morphism (数学抽象)
    ↓ [第一层：逻辑展开]
AtomicOperation 序列 (逻辑时序)
    ↓ [第二层：物理调度]  
RTMQInstruction 序列 (物理指令)
    ↓ [第三层：OASM生成]
OASM DSL 代码 (硬件控制)
```

### 第一层：Morphism 逻辑展开

将 Morphism 展开为 AtomicOperation 的时序序列：

```python
def expand_morphism(morphism: Morphism) -> list[ScheduledOperation]:
    """将 Morphism 展开为带时序的原子操作序列"""
    operations = []
    
    for channel, lane_ops in morphism.lanes.items():
        current_time = 0.0
        
        for op in lane_ops:
            scheduled_op = ScheduledOperation(
                operation=op,
                start_time=current_time,
                channel=channel
            )
            operations.append(scheduled_op)
            current_time += op.duration
    
    # 按时间排序，处理并行操作
    return sorted(operations, key=lambda op: op.start_time)
```

### 第二层：物理指令调度

将逻辑操作转换为物理执行指令：

```python
class RTMQCompiler:
    def compile_to_instructions(self, operations: list[ScheduledOperation]) -> list[RTMQInstruction]:
        """将调度操作转换为 RTMQ 物理指令"""
        instructions = []
        
        for i, sched_op in enumerate(operations):
            op = sched_op.operation
            
            # 生成参数写入指令
            write_instructions = self.generate_write_instructions(op)
            instructions.extend(write_instructions)
            
            # 生成时序等待指令
            if i > 0:
                wait_time = sched_op.start_time - prev_end_time
                if wait_time > 0:
                    instructions.append(TimerWait(wait_time))
            
            # 生成播放触发指令
            instructions.append(TriggerPlayback(op.channel, op.duration))
            
            prev_end_time = sched_op.start_time + op.duration
        
        return instructions

    def generate_write_instructions(self, op: AtomicOperation) -> list[RTMQInstruction]:
        """根据硬件参数生成写入指令"""
        if op.channel.device.__class__.__name__ == 'RWGDevice':
            return self._generate_rwg_write_instructions(op)
        elif op.channel.device.__class__.__name__ == 'TTLDevice':
            return self._generate_ttl_write_instructions(op)
        else:
            raise NotImplementedError(f"Unsupported device: {op.channel.device}")
    
    def _generate_rwg_write_instructions(self, op: AtomicOperation) -> list[RTMQInstruction]:
        """生成 RWG 参数写入指令"""
        instructions = []
        
        # 频率 Taylor 系数
        if 'freq_coeffs' in op.hardware_params:
            freq_coeffs = op.hardware_params['freq_coeffs']
            for i, coeff in enumerate(freq_coeffs):
                instructions.append(WriteRegister(f'FT{i}', coeff, op.channel))
        
        # 幅度 Taylor 系数  
        if 'amp_coeffs' in op.hardware_params:
            amp_coeffs = op.hardware_params['amp_coeffs']
            for i, coeff in enumerate(amp_coeffs):
                instructions.append(WriteRegister(f'AP{i}', coeff, op.channel))
        
        # 相位偏移
        if 'phase' in op.hardware_params:
            instructions.append(WriteRegister('POF', op.hardware_params['phase'], op.channel))
        
        return instructions
    
    def _generate_ttl_write_instructions(self, op: AtomicOperation) -> list[RTMQInstruction]:
        """生成 TTL 参数写入指令"""
        # TTL 相对简单，主要是状态设置
        ttl_value = 1 if isinstance(op.to_state, TTLOn) else 0
        return [WriteRegister('TTL_STATE', ttl_value, op.channel)]
```

### 第三层：OASM DSL 生成

将 RTMQ 指令转换为 OASM DSL 代码：

```python
class OASMGenerator:
    def __init__(self):
        self.channel_map = {}  # Channel -> OASM标识符映射
        self.label_counter = 0
    
    def generate_oasm(self, instructions: list[RTMQInstruction]) -> str:
        """生成 OASM DSL 代码"""
        oasm_lines = []
        
        # 生成头部声明
        oasm_lines.extend(self._generate_header())
        
        # 生成主程序
        oasm_lines.append("# Generated CatSeq OASM program")
        oasm_lines.append("main:")
        
        for instruction in instructions:
            oasm_line = self._translate_instruction(instruction)
            oasm_lines.append(f"    {oasm_line}")
        
        oasm_lines.append("    halt")
        
        return "\n".join(oasm_lines)
    
    def _translate_instruction(self, instruction: RTMQInstruction) -> str:
        """将单个 RTMQ 指令翻译为 OASM"""
        if isinstance(instruction, WriteRegister):
            return self._translate_write_register(instruction)
        elif isinstance(instruction, TriggerPlayback):
            return self._translate_trigger_playback(instruction)
        elif isinstance(instruction, TimerWait):
            return self._translate_timer_wait(instruction)
        else:
            raise NotImplementedError(f"Unknown instruction: {instruction}")
    
    def _translate_write_register(self, instr: WriteRegister) -> str:
        """翻译寄存器写入指令"""
        channel_id = self._get_channel_id(instr.channel)
        
        if instr.register.startswith('FT'):  # 频率 Taylor 系数
            taylor_idx = instr.register[2:]  # FT0 -> 0
            return f"set_freq_taylor {channel_id} {taylor_idx} {instr.value}"
            
        elif instr.register.startswith('AP'):  # 幅度 Taylor 系数
            taylor_idx = instr.register[2:]  # AP0 -> 0
            return f"set_amp_taylor {channel_id} {taylor_idx} {instr.value}"
            
        elif instr.register == 'POF':  # 相位偏移
            return f"set_phase {channel_id} {instr.value}"
            
        elif instr.register == 'TTL_STATE':  # TTL 状态
            return f"set_ttl {channel_id} {instr.value}"
            
        else:
            raise ValueError(f"Unknown register: {instr.register}")
    
    def _translate_trigger_playback(self, instr: TriggerPlayback) -> str:
        """翻译播放触发指令"""
        channel_id = self._get_channel_id(instr.channel)
        duration_cycles = self._duration_to_cycles(instr.duration)
        return f"trigger_waveform {channel_id} {duration_cycles}"
    
    def _translate_timer_wait(self, instr: TimerWait) -> str:
        """翻译等待指令"""
        wait_cycles = self._duration_to_cycles(instr.duration)
        return f"wait {wait_cycles}"
    
    def _get_channel_id(self, channel: Channel) -> str:
        """获取通道的 OASM 标识符"""
        if channel not in self.channel_map:
            if isinstance(channel.device, TTLDevice):
                self.channel_map[channel] = f"ttl_{len(self.channel_map)}"
            elif isinstance(channel.device, RWGDevice):
                self.channel_map[channel] = f"rwg_{len(self.channel_map)}"
            else:
                self.channel_map[channel] = f"ch_{len(self.channel_map)}"
        
        return self.channel_map[channel]
    
    def _duration_to_cycles(self, duration: float) -> int:
        """将时间转换为时钟周期数"""
        clock_freq = 250e6  # 250 MHz
        return int(duration * clock_freq)
    
    def _generate_header(self) -> list[str]:
        """生成 OASM 头部声明"""
        return [
            "# CatSeq Generated OASM Program",
            "# Clock frequency: 250 MHz",
            "",
            "# Channel declarations",
        ] + [
            f"# {channel.name} -> {oasm_id}" 
            for channel, oasm_id in self.channel_map.items()
        ] + [""]
```

### 完整翻译示例

```python
# 用户代码
ttl0 = Channel("TTL_TRIGGER", TTLDevice("TTL_0"))
rwg0 = Channel("RWG_CARRIER", RWGDevice("RWG_0"))

init_ttl = initialize(ttl0)
pulse_ttl = pulse(ttl0, 50e-6)  # 50μs 脉冲
ramp_rwg = rwg_sweep(rwg0, 100e6, 200e6, 100e-6)  # 100μs 扫频

# 并行执行：TTL 脉冲 + RWG 扫频
experiment = init_ttl @ (pulse_ttl | ramp_rwg)

# 编译为 OASM
compiler = RTMQCompiler()
generator = OASMGenerator()

# 三层翻译
operations = expand_morphism(experiment)
instructions = compiler.compile_to_instructions(operations) 
oasm_code = generator.generate_oasm(instructions)

print(oasm_code)
```

**生成的 OASM DSL 输出：**
```oasm
# CatSeq Generated OASM Program  
# Clock frequency: 250 MHz

# Channel declarations
# TTL_TRIGGER -> ttl_0
# RWG_CARRIER -> rwg_0

# Generated CatSeq OASM program
main:
    # Initialize TTL channel
    set_ttl ttl_0 0
    
    # Prepare RWG sweep parameters
    set_freq_taylor rwg_0 0 100000000.0    # F0: 100 MHz
    set_freq_taylor rwg_0 1 1000000000.0   # F1: 1 GHz/s (100MHz/100μs)
    set_freq_taylor rwg_0 2 0.0            # F2: 0
    set_freq_taylor rwg_0 3 0.0            # F3: 0
    set_amp_taylor rwg_0 0 0.5             # A0: 0.5 amplitude
    set_amp_taylor rwg_0 1 0.0             # A1: 0
    set_amp_taylor rwg_0 2 0.0             # A2: 0  
    set_amp_taylor rwg_0 3 0.0             # A3: 0
    set_phase rwg_0 0.0                    # Phase: 0
    
    # Prepare TTL pulse parameters
    set_ttl ttl_0 1                        # TTL ON
    
    # Wait 1 cycle (parameter setup time)
    wait 1
    
    # Trigger parallel execution: TTL pulse + RWG sweep
    trigger_waveform ttl_0 12500           # 50μs @ 250MHz = 12500 cycles
    trigger_waveform rwg_0 25000           # 100μs @ 250MHz = 25000 cycles
    
    # Wait for completion (100μs total)  
    wait 25000
    
    # Clean up: set TTL back to OFF
    set_ttl ttl_0 0
    
    halt
```

### OASM 翻译的关键特性

1. **精确时序映射**：时间单位精确转换为硬件时钟周期
2. **并行操作支持**：多通道同时触发，硬件并行执行
3. **参数预设置**：在波形触发前完成所有参数写入
4. **通道抽象**：自动映射 Channel 对象到 OASM 标识符
5. **错误检测**：编译期检查硬件约束和时序冲突

这样，整个 Framework Design 就包含了从数学抽象到硬件控制的完整链路！

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
8. **完整硬件控制链路**：从数学抽象到OASM DSL的三层翻译系统

### 关键创新点

1. **逻辑-物理分离**：用户只需关心波形播放逻辑，编译器处理底层时序调度
2. **原子操作抽象**：基于硬件segment的原子操作设计，直接对应物理实现  
3. **智能时序调度**：编译器自动计算参数写入时间，优化指令序列
4. **特殊约束支持**：支持锁频等特殊物理约束，确保关键实验条件
5. **组合律实现**：自动应用分配律和Identity插入，简化复杂时序组合
6. **三层编译架构**：Morphism → AtomicOperation → RTMQInstruction → OASM DSL
7. **硬件抽象映射**：Channel对象自动映射到具体硬件标识符
8. **精确时钟转换**：时间单位精确映射到硬件时钟周期

### 实际价值

- **提高实验可靠性**：数学验证确保实验序列的物理正确性
- **降低开发门槛**：类型安全和IDE支持提高开发效率
- **支持复杂实验**：无缝支持多通道并行和复杂时序组合
- **硬件抽象**：统一接口支持不同硬件类型和约束
- **错误预防**：编译时检查大幅减少运行时错误和硬件风险