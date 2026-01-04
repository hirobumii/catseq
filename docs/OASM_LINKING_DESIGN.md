# CatSeq 与手写 OASM 代码链接设计

## 使用场景

### 场景 1: 内联汇编优化

用户想在关键路径上插入手写的高度优化的 OASM 代码：

```python
# CatSeq 高层代码
initialize = ttl_init(ch1) @ ttl_init(ch2)

# 手写 OASM 优化片段（精确时序控制）
fast_pulse = InlineAsm("""
    AMK - TTL 2.0 $01      # TTL ON, 1 cycle
    wait_mu(2498)          # 精确等待 2498 cycles
    AMK - TTL 2.0 $00      # TTL OFF, 1 cycle
    # 总时长: 2500 cycles = 10μs
""", duration_cycles=2500)

# 组合使用
experiment = initialize >> fast_pulse >> measure
```

### 场景 2: 预编译函数库

用户有预编译的 OASM 函数库，封装复杂的底层操作：

```python
# 函数库：rtmq_lib.oasm
# FUNCTION fast_rabi_sequence
#   参数: $20 = rabi_frequency, $21 = duration
#   返回: $22 = fidelity
#   ...
# END_FUNCTION

# CatSeq 调用
from catseq.oasm import load_function

fast_rabi = load_function("rtmq_lib.oasm", "fast_rabi_sequence")
result = fast_rabi(frequency=5e6, duration=100e-6)
```

### 场景 3: 混合编译

部分用 CatSeq 编译，部分手写 OASM，链接成完整程序：

```python
# part1.py (CatSeq 编译)
initialization = compile_to_rtmq(ttl_init(ch1) @ ttl_init(ch2))

# part2.oasm (手写)
# LABEL measurement_sequence
#   ...
# END

# 链接
linker = RTMQLinker()
linker.add_module(initialization, name="init")
linker.add_oasm_file("part2.oasm")
final_program = linker.link(entry_point="init.main")
```

---

## 核心挑战

### 1. 符号解析

**问题**:
- CatSeq 生成的标签: `__rtmq_block_0`, `__rtmq_if_then_1`
- 手写 OASM 的标签: `LOOP_START`, `MEASUREMENT_ENTRY`
- 需要避免冲突，支持跨模块引用

**解决方案**: 符号表 + 命名空间

### 2. 调用约定

**问题**:
- 如何传递参数？（哪些 TCS 寄存器）
- 如何返回值？
- 谁负责保存/恢复寄存器？

**解决方案**: 定义标准调用约定（类似 C ABI）

### 3. 时间语义

**问题**:
- 手写 OASM 的时长如何告知 CatSeq？
- 如何保持逻辑时间连续性？

**解决方案**: 函数元数据声明 + 时间验证

### 4. 链接策略

**问题**:
- 何时链接？（编译时 vs 运行时）
- 如何合并代码？
- 如何处理重定位？

**解决方案**: 两阶段链接（编译时符号解析 + 最终汇编时地址绑定）

---

## 设计方案

### 1. OASM 对象文件格式

定义一个中间格式，包含代码 + 元数据：

```python
@dataclass
class OASMObject:
    """OASM 对象文件"""
    name: str  # 模块名
    code: List[OASMInstruction]  # 指令序列
    symbols: Dict[str, Symbol]   # 符号表
    relocations: List[Relocation]  # 重定位信息
    metadata: OASMMetadata  # 元数据

@dataclass
class Symbol:
    """符号定义"""
    name: str
    type: SymbolType  # LABEL, FUNCTION, VARIABLE
    offset: int  # 在 code 中的偏移
    size: int  # 大小（指令数）
    visibility: Visibility  # LOCAL, GLOBAL, EXTERNAL

@dataclass
class Relocation:
    """重定位条目"""
    offset: int  # 需要重定位的指令位置
    symbol: str  # 引用的符号名
    reloc_type: RelocationType  # ABSOLUTE, PC_RELATIVE

@dataclass
class OASMMetadata:
    """模块元数据"""
    duration_cycles: Optional[int]  # 总时长（如果确定）
    required_registers: Set[int]  # 使用的 TCS 寄存器
    clobbered_registers: Set[int]  # 会修改的寄存器
    call_convention: str  # 调用约定版本
```

---

### 2. 内联汇编实现

#### 2.1 用户 API

```python
from catseq.oasm import InlineAsm

def fast_pulse(channel: Channel, duration_us: float) -> Morphism:
    """手写 OASM 优化的 TTL 脉冲"""
    duration_cycles = int(duration_us * 250)  # 转换为时钟周期

    asm_code = InlineAsm(
        code=f"""
        # 精确 TTL 脉冲（手写优化）
        AMK - TTL 2.0 ${1 << channel.local_id:02X}  # TTL ON
        wait_mu({duration_cycles - 2})               # 精确等待
        AMK - TTL 2.0 $00                            # TTL OFF
        """,
        duration_cycles=duration_cycles,
        inputs={
            "channel": channel,
        },
        outputs={},
        clobbers=["ttl"],  # 会修改 TTL CSR
    )

    return Morphism.from_inline_asm(asm_code)
```

#### 2.2 编译流程

```python
class InlineAsm:
    """内联汇编片段"""

    def __init__(
        self,
        code: str,
        duration_cycles: int,
        inputs: Dict[str, Any] = None,
        outputs: Dict[str, str] = None,
        clobbers: List[str] = None,
    ):
        self.code = code
        self.duration_cycles = duration_cycles
        self.inputs = inputs or {}
        self.outputs = outputs or {}
        self.clobbers = clobbers or []

        # 解析 OASM 代码
        self.instructions = self._parse_oasm(code)

    def _parse_oasm(self, code: str) -> List[OASMInstruction]:
        """解析 OASM 文本 → 指令列表"""
        instructions = []
        for line in code.strip().split('\n'):
            line = line.split('#')[0].strip()  # 移除注释
            if not line:
                continue

            # 简单解析（实际需要更完善的 parser）
            parts = line.split()
            if parts[0] == 'AMK':
                instructions.append(OASMInstruction('AMK', parts[2:]))
            elif parts[0] == 'wait_mu':
                cycles = int(parts[0].split('(')[1].rstrip(')'))
                instructions.append(OASMInstruction('WAIT', [cycles]))
            # ... 其他指令

        return instructions

    def to_oasm_object(self) -> OASMObject:
        """转换为对象文件格式"""
        return OASMObject(
            name=f"inline_asm_{id(self)}",
            code=self.instructions,
            symbols={
                '__start': Symbol('__start', SymbolType.LABEL, 0, len(self.instructions)),
                '__end': Symbol('__end', SymbolType.LABEL, len(self.instructions), 0),
            },
            relocations=[],
            metadata=OASMMetadata(
                duration_cycles=self.duration_cycles,
                required_registers=set(),
                clobbered_registers=self._infer_clobbers(),
                call_convention='inline_v1',
            ),
        )

    def _infer_clobbers(self) -> Set[int]:
        """推断会修改的寄存器"""
        clobbers = set()
        for instr in self.instructions:
            if instr.opcode in ('AMK', 'ALU', 'MOV'):
                # 分析指令的目标寄存器
                # ...
                pass
        return clobbers
```

#### 2.3 集成到 Morphism

```python
class Morphism:
    @staticmethod
    def from_inline_asm(asm: InlineAsm) -> 'Morphism':
        """从内联汇编创建 Morphism"""
        # 转换为 OASM 对象
        oasm_obj = asm.to_oasm_object()

        # 包装为特殊的 AtomicMorphism
        atomic = AtomicMorphism(
            operation=InlineOASMOp(oasm_obj),
            domain=asm._infer_domain(),
            codomain=asm._infer_codomain(),
            duration_cycles=asm.duration_cycles,
        )

        return Morphism(_ast=AtomicNode(atomic))
```

---

### 3. 预编译函数库

#### 3.1 函数库格式

```asm
# rtmq_lib.oasm - 预编译函数库

# ========================================
# FUNCTION: fast_rabi_pulse
# 描述: 高性能 Rabi 振荡脉冲序列
# 参数:
#   $20: rabi_frequency (Hz, 32位整数)
#   $21: duration_cycles (时钟周期)
# 返回:
#   $22: actual_cycles (实际执行周期数)
# 约定:
#   - 保存 $23-$2F（调用者保存）
#   - 可修改 $30-$3F（临时寄存器）
#   - 保证时长 = duration_cycles ± 10
# ========================================
.FUNCTION fast_rabi_pulse
    # 保存寄存器
    MOV - $30 $23
    MOV - $31 $24

    # 配置 RWG 载波频率
    # ... 复杂的底层操作 ...
    AMK - RWG 3.0 $20  # 设置频率

    # 启动脉冲
    AMK - RWG 1.0 $01  # 启动

    # 精确等待
    MOV - $32 $21
    LOOP_START:
        SUB - $32 $32 $01
        LST - $33 $32 $00
        AMK P PTR $33 #LOOP_START  # 条件跳转

    # 停止脉冲
    AMK - RWG 1.0 $00

    # 返回实际周期数
    MOV - $22 $21

    # 恢复寄存器
    MOV - $23 $30
    MOV - $24 $31

    # 返回（假设调用者保存了 LNK）
    AMK P PTR 2.0 $LNK
.END_FUNCTION

# ========================================
# FUNCTION: precise_delay
# ...
# ========================================
.FUNCTION precise_delay
    # ...
.END_FUNCTION
```

#### 3.2 函数库编译器

```python
class OASMLibraryCompiler:
    """编译 OASM 函数库 → 对象文件"""

    def compile(self, source_path: str) -> OASMObject:
        """编译函数库"""
        with open(source_path, 'r') as f:
            source = f.read()

        # 解析函数定义
        functions = self._parse_functions(source)

        # 生成符号表
        symbols = {}
        code = []
        current_offset = 0

        for func in functions:
            # 函数入口符号
            symbols[func.name] = Symbol(
                name=func.name,
                type=SymbolType.FUNCTION,
                offset=current_offset,
                size=len(func.instructions),
                visibility=Visibility.GLOBAL,
            )

            # 添加指令
            code.extend(func.instructions)
            current_offset += len(func.instructions)

            # 函数元数据
            func_meta = FunctionMetadata(
                params=func.params,
                returns=func.returns,
                clobbers=func.clobbers,
                guaranteed_duration=func.duration_range,
            )
            symbols[f"{func.name}.__meta__"] = func_meta

        # 处理重定位
        relocations = self._collect_relocations(code, symbols)

        return OASMObject(
            name=Path(source_path).stem,
            code=code,
            symbols=symbols,
            relocations=relocations,
            metadata=OASMMetadata(
                duration_cycles=None,  # 库不确定总时长
                required_registers=set(range(0x20, 0x40)),
                clobbered_registers=set(),
                call_convention='rtmq_v1',
            ),
        )

    def _parse_functions(self, source: str) -> List[FunctionDef]:
        """解析 .FUNCTION ... .END_FUNCTION"""
        functions = []
        current_func = None

        for line in source.split('\n'):
            line = line.split('#')[0].strip()

            if line.startswith('.FUNCTION'):
                func_name = line.split()[1]
                current_func = FunctionDef(name=func_name)

            elif line.startswith('.END_FUNCTION'):
                functions.append(current_func)
                current_func = None

            elif current_func:
                # 解析参数声明（从注释提取）
                if '参数:' in line or 'Params:' in line:
                    # 提取参数元数据
                    pass
                else:
                    # 解析指令
                    instr = self._parse_instruction(line)
                    if instr:
                        current_func.instructions.append(instr)

        return functions

    def _collect_relocations(
        self, code: List[OASMInstruction], symbols: Dict[str, Symbol]
    ) -> List[Relocation]:
        """收集需要重定位的引用"""
        relocations = []

        for i, instr in enumerate(code):
            if instr.opcode == 'AMK' and 'PTR' in instr.operands:
                # 跳转指令，检查是否引用符号
                target = instr.operands[-1]
                if target.startswith('#'):  # 标签引用
                    label_name = target[1:]
                    if label_name not in symbols:
                        # 外部符号（需要链接时解析）
                        relocations.append(Relocation(
                            offset=i,
                            symbol=label_name,
                            reloc_type=RelocationType.PC_RELATIVE,
                        ))

        return relocations
```

#### 3.3 调用预编译函数

```python
from catseq.oasm import load_function, call_function

# 加载函数库
lib = load_function("rtmq_lib.oasm", "fast_rabi_pulse")

# 创建调用 Morphism
def rabi_pulse(frequency: float, duration: float) -> Morphism:
    """调用预编译的 Rabi 脉冲函数"""
    freq_int = int(frequency)
    duration_cycles = int(duration * 250)

    # 生成调用代码
    call_node = CallOASMFunction(
        function=lib,
        args={
            "$20": freq_int,
            "$21": duration_cycles,
        },
        returns={"actual_cycles": "$22"},
    )

    return Morphism.from_call(call_node, duration_cycles)
```

---

### 4. 链接器实现

#### 4.1 两阶段链接

**阶段 1: 符号解析**（编译时）

```python
class RTMQLinker:
    """RTMQ 对象文件链接器"""

    def __init__(self):
        self.modules: Dict[str, OASMObject] = {}
        self.global_symbols: Dict[str, Symbol] = {}

    def add_module(self, obj: OASMObject, name: str = None):
        """添加模块到链接器"""
        name = name or obj.name
        self.modules[name] = obj

        # 收集全局符号
        for sym_name, symbol in obj.symbols.items():
            if symbol.visibility == Visibility.GLOBAL:
                full_name = f"{name}.{sym_name}"
                if full_name in self.global_symbols:
                    raise LinkError(f"Duplicate symbol: {full_name}")
                self.global_symbols[full_name] = symbol

    def resolve_symbols(self):
        """解析所有符号引用"""
        for module_name, module in self.modules.items():
            for reloc in module.relocations:
                # 查找符号
                symbol_name = reloc.symbol
                full_name = f"{module_name}.{symbol_name}"

                if full_name not in self.global_symbols:
                    # 尝试跨模块查找
                    found = False
                    for other_name, other_symbol in self.global_symbols.items():
                        if other_name.endswith(f".{symbol_name}"):
                            full_name = other_name
                            found = True
                            break

                    if not found:
                        raise LinkError(f"Undefined symbol: {symbol_name}")

                # 记录解析结果
                reloc.resolved_symbol = self.global_symbols[full_name]
```

**阶段 2: 地址绑定**（最终汇编时）

```python
    def link(self, entry_point: str = "main") -> LinkedProgram:
        """链接所有模块，生成最终程序"""
        # 1. 解析符号
        self.resolve_symbols()

        # 2. 分配地址空间
        address_map = self._allocate_addresses()

        # 3. 应用重定位
        final_code = self._apply_relocations(address_map)

        # 4. 生成符号表（用于调试）
        symbol_table = self._build_symbol_table(address_map)

        return LinkedProgram(
            code=final_code,
            entry_point=address_map[entry_point],
            symbol_table=symbol_table,
        )

    def _allocate_addresses(self) -> Dict[str, int]:
        """分配每个模块和符号的最终地址"""
        address_map = {}
        current_address = 0

        for module_name, module in self.modules.items():
            # 模块起始地址
            module_start = current_address

            # 分配符号地址
            for sym_name, symbol in module.symbols.items():
                full_name = f"{module_name}.{sym_name}"
                address_map[full_name] = module_start + symbol.offset

            # 推进地址
            current_address += sum(len(instr) for instr in module.code)

        return address_map

    def _apply_relocations(self, address_map: Dict[str, int]) -> List[int]:
        """应用重定位，生成最终机器码"""
        final_code = []

        for module_name, module in self.modules.items():
            for i, instr in enumerate(module.code):
                # 检查是否需要重定位
                reloc = self._find_relocation(module, i)

                if reloc:
                    # 计算目标地址
                    symbol = reloc.resolved_symbol
                    target_addr = address_map[symbol.name]
                    current_addr = address_map[f"{module_name}.{symbol.name}"]

                    if reloc.reloc_type == RelocationType.PC_RELATIVE:
                        # PC 相对寻址
                        offset = target_addr - current_addr - 2
                        # 修改指令中的偏移量
                        instr = instr.with_offset(offset)

                    elif reloc.reloc_type == RelocationType.ABSOLUTE:
                        # 绝对地址
                        instr = instr.with_address(target_addr)

                # 编码指令
                final_code.append(instr.encode())

        return final_code
```

#### 4.2 调用约定

定义标准调用约定，保证 CatSeq 编译器和手写 OASM 的互操作性：

```python
class RTMQCallingConvention:
    """RTMQ 调用约定 v1

    寄存器分配:
      $00        - 常量 0
      $01        - 常量 -1
      $02-$0F    - 临时寄存器（调用者保存）
      $10-$1F    - 参数/返回值寄存器
        $10-$17  - 参数 1-8
        $18-$1F  - 返回值 1-8
      $20-$2F    - 保存寄存器（被调用者保存）
      $30-$FF    - 局部变量（栈分配）

    调用序列:
      1. 调用者: 加载参数到 $10-$17
      2. 调用者: 保存需要的临时寄存器 ($02-$0F)
      3. 调用者: 执行 CALL (MOV LNK; JMP target)
      4. 被调用者: 保存需要的寄存器 ($20-$2F)
      5. 被调用者: 执行函数体
      6. 被调用者: 加载返回值到 $18-$1F
      7. 被调用者: 恢复寄存器
      8. 被调用者: 返回 (JMP LNK)
      9. 调用者: 恢复临时寄存器
      10. 调用者: 读取返回值

    时间语义:
      - 被调用函数应保证总时长可预测
      - 元数据中声明 min_cycles 和 max_cycles
      - 调用者根据元数据调整逻辑时间
    """

    TEMP_REGS = range(0x02, 0x10)      # 临时寄存器
    PARAM_REGS = range(0x10, 0x18)     # 参数寄存器
    RETURN_REGS = range(0x18, 0x20)    # 返回值寄存器
    SAVED_REGS = range(0x20, 0x30)     # 保存寄存器
    LOCAL_REGS = range(0x30, 0x100)    # 局部变量
```

---

### 5. 完整示例

#### 5.1 混合编译示例

```python
# ========== 文件: experiment.py ==========
from catseq import *
from catseq.oasm import load_function, InlineAsm

# 加载预编译函数库
fast_rabi = load_function("rtmq_lib.oasm", "fast_rabi_pulse")

# CatSeq 高层代码
ch1 = Channel(Board("RWG_0"), 0)
initialization = (
    ttl_init(ch1)
    @ ttl_on(ch1)
    @ identity(ch1, 5e-6)  # 初始化等待
    @ ttl_off(ch1)
)

# 内联汇编优化片段
fast_measurement = InlineAsm(
    code="""
    # 超快速 ADC 读取（手写优化）
    AMK - ADC 1.0 $01      # 触发 ADC
    NOP H                  # 等待完成（异步）
    CSR - $10 ADC_DATA     # 读取结果到 $10
    """,
    duration_cycles=100,  # 保证 100 cycles 内完成
    outputs={"adc_value": "$10"},
    clobbers=["adc"],
)

# 组合实验
experiment = (
    initialization
    >> execute(fast_measurement)
    >> call_function(
        fast_rabi,
        frequency=5e6,
        duration=100e-6,
    )
)

# 编译
compiler = CatSeqCompiler()
rtmq_ir = compiler.compile(experiment)

# ========== 链接阶段 ==========
linker = RTMQLinker()

# 添加 CatSeq 编译的模块
linker.add_module(rtmq_ir.to_oasm_object(), name="main")

# 添加预编译库
lib_obj = OASMLibraryCompiler().compile("rtmq_lib.oasm")
linker.add_module(lib_obj, name="rtmq_lib")

# 链接
linked_program = linker.link(entry_point="main.__entry__")

# ========== 生成最终 OASM ==========
emitter = RTMQEmitter(linked_program)
final_asm = emitter.emit()

# 验证
print(emitter.verify_and_disassemble(final_asm))
```

#### 5.2 生成的汇编（示例）

```asm
# ========== 链接后的完整程序 ==========

# 模块: main (CatSeq 编译)
main.__entry__:
    # initialization
    AMK - TTL 2.0 $00      # ttl_init
    AMK - TTL 2.0 $01      # ttl_on
    wait_mu(1250)          # identity 5μs
    AMK - TTL 2.0 $00      # ttl_off

    # fast_measurement (内联汇编)
    AMK - ADC 1.0 $01      # 触发 ADC
    NOP H                  # 等待
    CSR - $10 ADC_DATA     # 读取到 $10

    # 调用 fast_rabi_pulse
    GLO - $10 #5000000     # 参数1: frequency
    GLO - $11 #25000       # 参数2: duration_cycles
    MOV - $02 $LNK         # 保存返回地址
    GLO - $FE #fast_rabi_pulse  # 加载函数地址
    AMK P PTR 3.0 $FE      # 跳转
    MOV - $LNK $02         # 恢复
    # 返回值在 $18

    # 实验结束
    NOP -

# 模块: rtmq_lib (预编译库)
fast_rabi_pulse:
    MOV - $30 $20          # 保存 $20
    MOV - $31 $21          # 保存 $21

    # 配置 RWG
    AMK - RWG 3.0 $10      # 频率
    AMK - RWG 1.0 $01      # 启动

    # 精确等待
    MOV - $32 $11
.Lloop_start:
    SUB - $32 $32 $01
    LST - $33 $32 $00
    GLO - $FE #.Lloop_start
    AMK P PTR $33 $FE

    # 停止
    AMK - RWG 1.0 $00

    # 返回
    MOV - $18 $11          # 返回实际周期数
    MOV - $20 $30          # 恢复
    MOV - $21 $31
    AMK P PTR 2.0 $LNK     # 返回
```

---

## 6. 实施计划

### Phase 3: 基础支持

- [ ] 定义 `OASMObject` 数据结构
- [ ] 实现 `InlineAsm` 基本功能
- [ ] 实现简单的符号表管理
- [ ] 测试：CatSeq + 内联汇编

### Phase 4: 函数库支持

- [ ] 设计调用约定（`RTMQCallingConvention`）
- [ ] 实现 `OASMLibraryCompiler`
- [ ] 实现 `load_function()` 和 `call_function()`
- [ ] 测试：调用预编译函数

### Phase 5: 完整链接器

- [ ] 实现 `RTMQLinker`（符号解析 + 地址分配）
- [ ] 实现重定位支持
- [ ] 完善错误处理（未定义符号、冲突等）
- [ ] 测试：多模块链接

### Phase 6: 调试和优化

- [ ] 生成调试信息（符号表 + 行号映射）
- [ ] 链接时优化（死代码消除、内联）
- [ ] 性能测试和优化

---

## 7. 技术细节

### 7.1 时间语义处理

**问题**: 手写 OASM 的时长如何与 CatSeq 的逻辑时间对齐？

**解决方案**: 函数元数据声明 + 编译时验证

```python
class FunctionMetadata:
    """函数元数据"""
    min_cycles: int  # 最小执行周期
    max_cycles: int  # 最大执行周期
    is_deterministic: bool  # 时长是否确定

# 内联汇编声明
fast_pulse = InlineAsm(
    code="...",
    duration_cycles=2500,  # 确定时长
)

# 预编译函数声明
# .FUNCTION fast_rabi_pulse
#   @duration: 1000-1100 cycles  # 时长范围
# .END_FUNCTION

# 编译器处理
if func.is_deterministic:
    # 确定时长：可以精确对齐
    total_duration += func.duration_cycles
else:
    # 不确定时长：保守估计 + 运行时验证
    total_duration += func.max_cycles
    emit_runtime_check(func.min_cycles, func.max_cycles)
```

### 7.2 寄存器冲突检测

**问题**: CatSeq 编译器分配的寄存器与手写 OASM 冲突？

**解决方案**: 调用约定 + 寄存器使用声明

```python
# CatSeq 编译器遵守调用约定
class TCSRegisterAllocator:
    def allocate(self):
        # 避开调用约定保留的寄存器
        # 只使用 $30-$FF（局部变量区）
        if self.next_reg < 0x30:
            self.next_reg = 0x30
        return self.next_reg

# 手写 OASM 声明使用的寄存器
fast_pulse = InlineAsm(
    code="...",
    clobbers=["ttl", "$30", "$31"],  # 会修改 TTL CSR 和 $30/$31
)

# 链接器检查冲突
def check_register_conflicts(module1, module2):
    clobbers1 = module1.metadata.clobbered_registers
    required2 = module2.metadata.required_registers

    conflicts = clobbers1 & required2
    if conflicts:
        raise LinkError(f"Register conflict: {conflicts}")
```

### 7.3 跨模块优化

**可能的优化**（链接时）:

1. **内联小函数**:
   ```python
   # 小函数（< 10 条指令）自动内联
   if len(func.code) < 10:
       inline_function(func)
   ```

2. **死代码消除**:
   ```python
   # 移除未被引用的函数
   for func in functions:
       if func.name not in referenced_symbols:
           remove_function(func)
   ```

3. **跳转优化**:
   ```python
   # 优化跳转链: JMP A; A: JMP B → JMP B
   optimize_jump_chains()
   ```

---

## 8. 替代方案对比

### 方案 A: 完整链接器（本方案）

**优点**:
- ✅ 完全支持混合编译
- ✅ 标准调用约定，可扩展
- ✅ 支持预编译库复用

**缺点**:
- ❌ 实现复杂度高
- ❌ 需要定义和维护调用约定

**适用场景**: 复杂项目，需要高度优化的底层代码

---

### 方案 B: 简化内联汇编（仅支持内联）

**优点**:
- ✅ 实现简单
- ✅ 足够应对大部分优化场景

**缺点**:
- ❌ 不支持预编译库
- ❌ 不支持跨模块调用

**适用场景**: 简单项目，只需要少量优化

---

### 方案 C: 外部链接器（使用 LLVM lld）

**优点**:
- ✅ 成熟的链接器实现
- ✅ 完整的优化支持

**缺点**:
- ❌ 需要适配 RTMQ 目标（工作量大）
- ❌ 重量级依赖

**适用场景**: 长期项目，需要工业级链接器

---

## 9. 推荐策略

### 阶段 1: 最小可行方案（Phase 3-4）

**只实现内联汇编**:
- `InlineAsm` 基础功能
- 简单的符号管理（局部标签）
- 无跨模块调用

**评估**: 观察用户需求，是否需要预编译库支持

---

### 阶段 2: 完整方案（Phase 5-6，如需要）

如果用户有强烈需求：
- 实现完整链接器
- 定义标准调用约定
- 支持预编译函数库

---

## 10. 总结

**核心设计**:
1. **对象文件格式**: `OASMObject` - 代码 + 符号表 + 重定位信息
2. **内联汇编**: `InlineAsm` - 简单场景的快速解决方案
3. **预编译库**: `.oasm` 文件 + 函数元数据声明
4. **链接器**: 两阶段链接（符号解析 + 地址绑定）
5. **调用约定**: `RTMQCallingConvention` - 保证互操作性

**实施建议**:
- ✅ **Phase 3-4**: 先实现内联汇编（满足 80% 需求）
- ⚠️ **Phase 5-6**: 根据实际需求决定是否实现完整链接器
- ✅ **始终保持**: 清晰的架构边界（xdsl 高层 / OASM 底层）

---

**文档版本**: 1.0
**创建日期**: 2026-01-05
**作者**: Claude (Sonnet 4.5)
