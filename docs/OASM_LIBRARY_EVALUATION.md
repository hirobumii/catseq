# OASM Library Implementation Evaluation

## Executive Summary

**结论**: OASM 库作为**纯汇编器后端**完全可用，但所有高层抽象必须在 xdsl 层面实现。

**核心原则**:
- ✅ **OASM 定位**: 纯粹的汇编器 - 指令编码 + 标签解析 + 机器码生成
- ✅ **xdsl 职责**: 所有高层抽象 - 变量系统 + 延迟求值 + 控制流 + 优化
- ❌ **不使用**: OASM 的 `expr` 延迟求值、高层控制流 API

**推荐使用的 OASM 组件**:
- ✅ 底层指令生成: `amk()`, `alu()`, `mov()`, `chi()`, `clo()`, `glo()`
- ✅ 标签管理: `label()` - 仅用于最终汇编阶段的位置解析
- ✅ 汇编器上下文: `assembler` - 管理汇编缓冲区
- ✅ 反汇编器: `disassembler` - 验证和调试

---

## 1. 架构边界明确化

### 1.1 正确的编译流程

```
┌─────────────────────────────────────────────────┐
│  xdsl/MLIR 层 (我们的职责)                       │
│  - 变量系统 (SSA values, TCS 寄存器分配)          │
│  - 延迟求值 (MLIR operations, 优化 passes)       │
│  - 控制流 (qprog.if, qprog.for → rtmq.branch)   │
│  - 优化 (死代码消除, 常量折叠, 循环展开)          │
│  - 标签分配 (唯一标签名生成)                     │
└─────────────────┬───────────────────────────────┘
                  │ Lowering 完成后
                  │ 所有 SSA values → TCS 寄存器
                  │ 所有分支 → 明确的标签和跳转
                  ↓
┌─────────────────────────────────────────────────┐
│  OASM 层 (库提供)                                │
│  - 指令编码 (amk, alu, mov → 机器码)             │
│  - 标签位置解析 (label 名称 → 字节偏移)          │
│  - 机器码生成 (二进制输出)                       │
│  - 反汇编 (验证输出)                             │
└─────────────────────────────────────────────────┘
```

### 1.2 错误的做法 ❌

```python
# ❌ 错误：在 OASM 层使用 expr 延迟求值
offset = expr(some_value)
amk('ptr', '3.0', offset)

# ❌ 错误：在 OASM 层使用高层控制流
with If(condition):
    ttl_on()

# ❌ 错误：依赖 OASM 的前向引用自动解析
target = label('undefined_label', put=False)  # 返回 expr
br_if(condition, target)
```

### 1.3 正确的做法 ✅

```python
# ✅ 正确：在 xdsl IR 中表示所有逻辑
# catseq dialect → qprog dialect → qctrl dialect → rtmq dialect
# 到 rtmq dialect 时：
# - 所有变量已分配 TCS 寄存器
# - 所有分支已转换为标签 + 跳转指令
# - 标签名称已确定（无前向引用）

# ✅ 正确：OASM 只做最后一步（汇编）
emitter = RTMQEmitter(rtmq_module)
with assembler() as asm_ctx:
    # 1. 先扫描所有基本块，定义所有标签
    for block in rtmq_module.blocks:
        label(block.label_name)  # 标签名已知，直接定义

    # 2. 生成指令
    for block in rtmq_module.blocks:
        for op in block.ops:
            if isinstance(op, RTMQ_AMK_Op):
                amk(op.csr, op.mask, op.value)
            elif isinstance(op, RTMQ_Jump_Op):
                # 标签位置已知（第一遍扫描）
                target_pos = get_label_position(op.target)
                offset = target_pos - current_position - 2
                glo('$FE', offset)  # 临时寄存器
                amk('ptr', '3.0', '$FE')
```

**关键区别**:
- **xdsl 层**: 符号化表示（`%value`, `^block_label`）
- **OASM 层**: 物理表示（TCS 寄存器地址、字节偏移）

---

## 2. OASM 组件详细评估

### 2.1 应该使用的组件 ✅

#### 底层指令生成

| 函数 | 用途 | 质量评分 | 使用方式 |
|------|------|----------|----------|
| `amk(csr, mask, val, hp)` | CSR 位掩码操作 | ⭐⭐⭐⭐ | 生成 AMK 指令（TTL, PTR, etc.） |
| `alu(opc, rd, r0, r1)` | ALU 运算 | ⭐⭐⭐⭐ | 算术、逻辑、比较指令 |
| `mov(rd, r0, hp)` | 数据移动 | ⭐⭐⭐⭐ | TCS 寄存器加载 |
| `chi(csr, imm)` | 高 20 位立即数 | ⭐⭐⭐⭐ | 大立即数的高位 |
| `clo(csr, imm, hp)` | 低 20 位立即数 | ⭐⭐⭐⭐ | 大立即数的低位 |
| `glo(rd, imm)` | TCS 立即数加载 | ⭐⭐⭐⭐ | 加载 20 位有符号数到 TCS |

**使用示例**:

```python
# TTL 控制
amk('ttl', '2.0', '$00')  # TTL OFF (位字段 = $00)
amk('ttl', '2.0', '$01')  # TTL ON (位字段 = $01)

# 比较指令
alu('LST', '$10', '$20', '$21')  # $10 = ($20 < $21) ? -1 : 0

# 加载立即数
glo('$10', 1000)  # $10 = 1000 (20位范围内)

# 大立即数
chi('tim', 0x000)      # TIM[63:32] = 0
clo('tim', 0x0270F)    # TIM[31:0] = 10000

# 条件跳转
glo('$FE', offset)     # 加载偏移
amk('ptr', '$10', '$FE')  # 如果 $10 == -1 则跳转
```

---

#### 标签管理（限定用途）

| 函数 | 用途 | 限制 |
|------|------|------|
| `label(tag, put=True)` | 定义标签位置 | ⚠️ 只在最终汇编阶段使用 |

**正确使用**:

```python
# ✅ 正确：标签名已知，直接定义
label('block_0')
amk('ttl', '2.0', '$01')

label('block_1')
amk('ttl', '2.0', '$00')

# ✅ 正确：计算标签位置用于跳转
block_1_pos = get_label_position('block_1')  # 从预扫描获取
offset = block_1_pos - current_pos - 2
glo('$FE', offset)
amk('ptr', '3.0', '$FE')
```

**错误使用**:

```python
# ❌ 错误：依赖 OASM expr 前向引用
target = label('undefined_label', put=False)  # 返回 expr
amk('ptr', '3.0', target)  # 依赖 expr 延迟求值

# 问题：
# 1. expr 机制是 OASM 内部实现，我们不应依赖
# 2. 前向引用应在 xdsl IR 中解析（SSA + CFG）
# 3. 到 OASM 时所有标签位置应已知
```

**替代方案**:

```python
# ✅ 在 MLIR lowering 阶段解析前向引用
class RTMQEmitter:
    def emit(self, rtmq_module):
        # Phase 1: 收集所有标签位置
        label_positions = {}
        current_pos = 0
        for block in rtmq_module.blocks:
            label_positions[block.label] = current_pos
            current_pos += estimate_block_size(block)

        # Phase 2: 生成指令
        with assembler():
            for block in rtmq_module.blocks:
                label(block.label)  # 定义标签

                for op in block.ops:
                    if isinstance(op, RTMQ_Jump_Op):
                        # 标签位置已知
                        target_pos = label_positions[op.target]
                        offset = target_pos - current_pos - 2
                        glo('$FE', offset)
                        amk('ptr', '3.0', '$FE')
```

---

#### 汇编器上下文

```python
class assembler:
    """汇编器上下文管理器"""
    def __init__(self, cfg=None, multi=None):
        self.cfg = cfg  # 配置（核心类型、接口等）
        self.asm = []   # 汇编缓冲区

    def __enter__(self):
        # 切换到新的汇编上下文
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        # 恢复上下文
        pass

    def run(self, disa=False):
        """执行汇编代码（上传到硬件或反汇编）"""
        if disa:
            print(disassembler()(self.asm, 0))
        # ... 硬件接口调用
```

**使用方式**:

```python
# ✅ 正确使用
with assembler() as asm_ctx:
    label('entry')
    amk('ttl', '2.0', '$01')
    # ... 更多指令

# 反汇编验证
asm_ctx.run(disa=True)

# 上传到硬件（如果有接口）
# asm_ctx.run()
```

**质量**: ⭐⭐⭐⭐ (4/5) - 清晰的上下文管理

---

#### 反汇编器

```python
class disassembler:
    """机器码 → 汇编文本"""
    def __call__(self, code, idx_str=None, idx_wid=4):
        # code: List[int] - 32位机器码列表
        # idx_str: 起始地址（用于显示）
        # idx_wid: 地址宽度

        # 返回可读的汇编文本
        # 例如:
        # 0000: AMK - TTL 2.0 $01
        # 0001: CHI - TIM 0x000_00000
        # 0002: CLO - TIM 0x000_0270F
```

**使用方式**:

```python
# 验证生成的代码
disa = disassembler()
asm_text = disa(asm_ctx.asm, 0, 4)
print(asm_text)

# 对比预期输出
assert 'AMK - TTL 2.0 $01' in asm_text
```

**质量**: ⭐⭐⭐⭐⭐ (5/5) - 调试必备，实现完善

---

### 2.2 不应该使用的组件 ❌

#### OASM 的 `expr` 延迟求值

**为什么不用**:
1. **职责错位**: 延迟求值应在 xdsl IR 层面（SSA values）
2. **类型不安全**: `expr` 是动态类型，无编译时检查
3. **调试困难**: 求值错误发生在运行时，堆栈难以追踪
4. **不可控**: `expr` 内部逻辑复杂（150+ 行），副作用难以预测

**xdsl 替代方案**:

```python
# ✅ xdsl SSA values（编译时类型安全）
@irdl_op_definition
class RTMQ_Add_Op(IRDLOperation):
    name = "rtmq.add"
    rd = operand_def(TCSRegisterType)   # 类型：TCS 寄存器
    r0 = operand_def(TCSRegisterType)
    r1 = operand_def(TCSRegisterType)
    result = result_def(TCSRegisterType)

# SSA 形式（延迟求值在 IR 优化中完成）
%0 = rtmq.load_imm 10
%1 = rtmq.load_imm 20
%2 = rtmq.add %0, %1  # 延迟：优化 pass 可能折叠为常量 30

# Lowering 到 OASM 时，SSA values 已求值
# %0 → $20 (TCS 寄存器)
# %1 → $21
# %2 → $22
glo('$20', 10)
glo('$21', 20)
alu('ADD', '$22', '$20', '$21')
```

---

#### OASM 高层控制流

**不使用**:
- `if_()` / `else_()` / `elif_()`
- `for_()` / `while_()`
- `If` / `For` / `While` (context manager)
- `block()` / `loop()` / `end()`

**原因**:
1. **绕过 MLIR 编译流程** - 无法在 IR 层优化
2. **时序不可控** - 循环展开、分支合并在汇编层发生
3. **与我们的架构冲突** - 违反 "OASM 仅作为汇编器" 原则

**xdsl 替代方案**:

```python
# ✅ 在 qprog dialect 表示控制流
@irdl_op_definition
class ForOp(IRDLOperation):
    name = "qprog.for"
    count = operand_def(IntegerType)
    body = region_def()

# ✅ Lowering 到 rtmq dialect（显式标签 + 跳转）
# qprog.for %count {
#   qprog.execute %morphism
# }
# ↓
# rtmq.label "loop_start"
# rtmq.branch_if %condition, "loop_body", "loop_end"
# rtmq.label "loop_body"
# ... morphism code ...
# rtmq.jump "loop_start"
# rtmq.label "loop_end"

# ✅ 最终 OASM（机械翻译）
label('loop_start')
alu('LST', '$10', '$counter', '$limit')  # $10 = counter < limit
glo('$FE', loop_body_offset)
amk('ptr', '$10', '$FE')  # 如果 < 则跳转到 body
glo('$FE', loop_end_offset)
amk('ptr', '3.0', '$FE')  # 否则跳转到 end

label('loop_body')
# ... 循环体 ...
glo('$FE', loop_start_offset)
amk('ptr', '3.0', '$FE')  # 跳回开始

label('loop_end')
```

---

#### OASM 的 `table` 和 `context` 元编程

**不直接使用**:
- `table` 类 - 混合列表/字典，类型不安全
- `context` 类 - 栈式状态管理
- `flow` 类 - 控制流元编程

**原因**:
- 这些是 OASM 内部基础设施
- 我们应该用 xdsl 的类型系统和 IR 结构

**xdsl 替代方案**:

```python
# ✅ xdsl 类型系统
@irdl_attr_definition
class TCSRegisterType(ParametrizedAttribute):
    name = "rtmq.tcs_register"
    reg_id = ParameterDef(IntAttr)  # 寄存器 ID ($00-$FF)

# ✅ xdsl Region 管理（替代 OASM context 栈）
@irdl_op_definition
class FunctionOp(IRDLOperation):
    name = "rtmq.function"
    body = region_def()  # 自动管理嵌套区域

# ✅ xdsl SSA values（替代 OASM table）
%0 = rtmq.load_imm 10
%1 = rtmq.add %0, %0
```

---

## 3. 集成策略

### 3.1 Phase 3: rtmq → OASM 代码生成器

**文件**: `catseq/mlir/codegen/rtmq_emitter.py`

```python
from oasm.rtmq2 import (
    assembler, label, amk, mov, alu,
    chi, clo, glo, disassembler
)
from xdsl.ir import MLContext, Operation, Block
from catseq.mlir.dialects.rtmq import *

class RTMQEmitter:
    """RTMQ IR → OASM 汇编代码生成器

    设计原则:
    1. OASM 只做最后一步（指令编码 + 标签位置解析）
    2. 所有高层逻辑在 MLIR lowering 中完成
    3. 到此阶段，所有 SSA values 已分配 TCS 寄存器
    """

    def __init__(self, rtmq_module: ModuleOp):
        self.module = rtmq_module
        self.label_positions: Dict[str, int] = {}
        self.current_pos = 0

    def emit(self) -> assembler:
        """生成 OASM 汇编代码"""
        # Phase 1: 预扫描，计算所有标签位置
        self._compute_label_positions()

        # Phase 2: 生成指令
        with assembler() as asm_ctx:
            for func in self.module.ops:
                if isinstance(func, RTMQ_Function_Op):
                    self._emit_function(func)

        return asm_ctx

    def _compute_label_positions(self):
        """预扫描：计算所有标签的字节偏移"""
        pos = 0
        for func in self.module.ops:
            for block in func.body.blocks:
                label_name = block.label_attr.data
                self.label_positions[label_name] = pos
                # 估算块大小（每条指令 1 字节）
                pos += len(block.ops)

    def _emit_function(self, func_op: RTMQ_Function_Op):
        """生成函数代码"""
        func_name = func_op.sym_name.data
        label(func_name)  # 函数入口标签

        for block in func_op.body.blocks:
            self._emit_block(block)

    def _emit_block(self, block: Block):
        """生成基本块代码"""
        # 定义块标签
        block_label = block.label_attr.data
        label(block_label)

        # 生成指令
        for op in block.ops:
            self._emit_operation(op)

    def _emit_operation(self, op: Operation):
        """生成单条操作"""
        if isinstance(op, RTMQ_AMK_Op):
            self._emit_amk(op)
        elif isinstance(op, RTMQ_ALU_Op):
            self._emit_alu(op)
        elif isinstance(op, RTMQ_LoadImm_Op):
            self._emit_load_imm(op)
        elif isinstance(op, RTMQ_Jump_Op):
            self._emit_jump(op)
        elif isinstance(op, RTMQ_Branch_Op):
            self._emit_branch(op)
        else:
            raise ValueError(f"Unknown RTMQ op: {op.name}")

    def _emit_amk(self, op: RTMQ_AMK_Op):
        """生成 AMK 指令

        例如: rtmq.amk "ttl", "2.0", %value
        → amk('ttl', '2.0', '$20')  # %value 已分配到 $20
        """
        csr = op.csr.data
        mask = op.mask.data
        value_reg = self._get_tcs_register(op.value)

        amk(csr, mask, value_reg)

    def _emit_alu(self, op: RTMQ_ALU_Op):
        """生成 ALU 指令

        例如: %result = rtmq.alu "ADD", %r0, %r1
        → alu('ADD', '$22', '$20', '$21')
        """
        opcode = op.opcode.data
        rd = self._get_tcs_register(op.result)
        r0 = self._get_tcs_register(op.r0)
        r1 = self._get_tcs_register(op.r1)

        alu(opcode, rd, r0, r1)

    def _emit_load_imm(self, op: RTMQ_LoadImm_Op):
        """生成立即数加载

        例如: %value = rtmq.load_imm 1000
        → glo('$20', 1000)  # 20位范围内

        或: %value = rtmq.load_imm 0x12345678
        → chi('&tmp', 0x123)   # 高位
        → clo('&tmp', 0x45678) # 低位
        → csr('$20', '&tmp')   # 加载到 TCS
        """
        rd = self._get_tcs_register(op.result)
        imm = op.immediate.data

        if -0x80000 <= imm < 0x80000:  # 20位范围
            glo(rd, imm)
        else:  # 32位大立即数
            # 使用临时 CSR
            chi('&tmp', (imm >> 20) & 0xFFF)
            clo('&tmp', imm & 0xFFFFF)
            mov(rd, '&tmp')

    def _emit_jump(self, op: RTMQ_Jump_Op):
        """生成无条件跳转

        例如: rtmq.jump ^block_1
        → glo('$FE', offset)
        → amk('ptr', '3.0', '$FE')
        """
        target_label = op.target.data
        offset = self._compute_offset(target_label)

        glo('$FE', offset)  # 临时寄存器
        amk('ptr', '3.0', '$FE')  # PTR 直接赋值模式（无条件）

    def _emit_branch(self, op: RTMQ_Branch_Op):
        """生成条件跳转

        例如: rtmq.branch %condition, ^then, ^else
        → glo('$FE', then_offset)
        → amk('ptr', %condition, '$FE')  # 条件 == -1 时跳转到 then
        → glo('$FE', else_offset)
        → amk('ptr', '3.0', '$FE')       # 否则跳转到 else
        """
        condition_reg = self._get_tcs_register(op.condition)
        then_label = op.then_target.data
        else_label = op.else_target.data

        # 条件跳转到 then
        then_offset = self._compute_offset(then_label)
        glo('$FE', then_offset)
        amk('ptr', condition_reg, '$FE')

        # 无条件跳转到 else（如果上面没跳）
        else_offset = self._compute_offset(else_label)
        glo('$FE', else_offset)
        amk('ptr', '3.0', '$FE')

    def _get_tcs_register(self, value: SSAValue) -> str:
        """获取 SSA value 分配的 TCS 寄存器

        在 MLIR lowering 阶段，所有 SSA values 已分配物理寄存器
        这里只是查表获取
        """
        # 从 SSA value 的属性中获取寄存器分配
        reg_attr = value.attributes.get('tcs_register')
        if reg_attr is None:
            raise ValueError(f"SSA value {value} not allocated to TCS register")

        reg_id = reg_attr.reg_id.data
        return f"${reg_id:02X}"

    def _compute_offset(self, target_label: str) -> int:
        """计算跳转偏移

        offset = target_position - current_position - 2
        （-2 是因为 PTR 跳转的基准是下下条指令）
        """
        target_pos = self.label_positions[target_label]
        offset = target_pos - self.current_pos - 2
        self.current_pos += 2  # glo + amk 两条指令
        return offset

    def verify_and_disassemble(self, asm_ctx: assembler) -> str:
        """验证和反汇编"""
        disa = disassembler()
        asm_text = disa(asm_ctx.asm, 0)
        print("=== RTMQ Assembly ===")
        print(asm_text)
        return asm_text
```

**使用示例**:

```python
# MLIR rtmq IR（已完成 lowering 和寄存器分配）
rtmq_module = ...  # ModuleOp 包含 RTMQ_Function_Op

# 生成 OASM 代码
emitter = RTMQEmitter(rtmq_module)
asm_ctx = emitter.emit()

# 验证输出
asm_text = emitter.verify_and_disassemble(asm_ctx)

# 上传到硬件（如果需要）
# asm_ctx.run()
```

---

### 3.2 关键设计决策

#### 决策 1: 两遍扫描

**原因**: 避免依赖 OASM 的 `expr` 前向引用

```python
# Phase 1: 计算所有标签位置
self._compute_label_positions()  # 填充 self.label_positions

# Phase 2: 生成指令
# 所有跳转偏移都可以直接计算（无需 expr）
offset = self.label_positions[target] - current_pos - 2
```

**优点**:
- ✅ 完全控制：不依赖 OASM 内部机制
- ✅ 可预测：偏移计算在我们的代码中
- ✅ 可调试：标签位置可以打印验证

---

#### 决策 2: SSA values → TCS 寄存器映射在 MLIR 层完成

**原因**: xdsl 提供完整的寄存器分配框架

```python
# ✅ 在 MLIR lowering pass 中分配寄存器
class TCSRegisterAllocationPass(ModulePass):
    def apply(self, ctx, module):
        allocator = TCSAllocator()  # 我们实现的分配器

        for value in module.walk(SSAValue):
            reg_id = allocator.allocate()
            value.attributes['tcs_register'] = TCSRegisterAttr(reg_id)

# ✅ OASM 层只查表
reg_id = value.attributes['tcs_register'].reg_id.data
return f"${reg_id:02X}"
```

**不这样做** ❌:

```python
# ❌ 在 OASM 层分配寄存器
# 问题：寄存器分配是编译器优化的一部分，应在 IR 层完成
reg_counter = 0x20
def allocate_register():
    global reg_counter
    reg = reg_counter
    reg_counter += 1
    return f"${reg:02X}"
```

---

#### 决策 3: 不使用 OASM 的高层控制流

**原因**: 违反 MLIR 编译流程

```python
# ❌ 不这样做
with If(condition_reg):
    amk('ttl', '2.0', '$01')

# ✅ 应该这样做
# 1. 在 qprog dialect 中表示 if
@irdl_op_definition
class IfOp(IRDLOperation):
    name = "qprog.if"
    condition = operand_def(...)
    then_region = region_def()
    else_region = region_def()

# 2. Lowering 到 rtmq dialect（显式分支）
rtmq.branch %condition, ^then, ^else

# 3. OASM 机械翻译
glo('$FE', then_offset)
amk('ptr', condition_reg, '$FE')
glo('$FE', else_offset)
amk('ptr', '3.0', '$FE')
```

---

## 4. 测试策略

### 4.1 单元测试：OASM 指令生成

```python
def test_amk_instruction():
    """测试 AMK 指令生成"""
    with assembler() as ctx:
        amk('ttl', '2.0', '$01')

    # 验证机器码
    assert len(ctx.asm) == 1

    # 反汇编验证
    disa = disassembler()
    asm_text = disa(ctx.asm, 0)
    assert 'AMK - TTL 2.0 $01' in asm_text
```

### 4.2 集成测试：端到端编译

```python
def test_simple_ttl_pulse():
    """测试简单 TTL 脉冲编译"""
    # 1. 构造 RTMQ IR
    rtmq_ir = build_ttl_pulse_ir()

    # 2. 生成 OASM
    emitter = RTMQEmitter(rtmq_ir)
    asm_ctx = emitter.emit()

    # 3. 验证输出
    asm_text = emitter.verify_and_disassemble(asm_ctx)

    # 4. 检查关键指令
    assert 'AMK - TTL 2.0 $01' in asm_text  # TTL ON
    assert 'CHI - TIM' in asm_text          # Timer 高位
    assert 'CLO - TIM' in asm_text          # Timer 低位
    assert 'AMK - TTL 2.0 $00' in asm_text  # TTL OFF
```

### 4.3 回归测试：对比旧编译器

```python
def test_compatibility_with_legacy_compiler():
    """验证新编译器与旧编译器输出一致"""
    pulse = ttl_on(ch1) @ identity(ch1, 10e-6) @ ttl_off(ch1)

    # 旧编译器
    oasm_calls_old = compile_to_oasm_legacy(pulse)

    # 新编译器
    rtmq_ir = compile_to_rtmq_ir(pulse)
    emitter = RTMQEmitter(rtmq_ir)
    asm_ctx = emitter.emit()
    oasm_calls_new = extract_oasm_calls(asm_ctx)

    # 对比（允许指令顺序调整，但功能等价）
    assert functionally_equivalent(oasm_calls_old, oasm_calls_new)
```

---

## 5. 总结

### 5.1 最终评估

| 方面 | 评分 | 说明 |
|------|------|------|
| **OASM 底层工具质量** | ⭐⭐⭐⭐ | 指令生成、标签管理、反汇编完善 |
| **适合作为汇编器后端** | ⭐⭐⭐⭐⭐ | **完美契合**，职责清晰 |
| **高层 API（不用）** | ⭐⭐⭐ | 功能完整但架构冲突 |
| **类型安全性** | ⭐⭐ | 无类型注解（不影响我们，因为只用底层） |
| **文档质量** | ⭐⭐ | 缺少文档（不影响，函数签名清晰） |
| **整体推荐度** | ⭐⭐⭐⭐⭐ | **强烈推荐**作为汇编器后端 |

### 5.2 核心结论

✅ **OASM 库完全满足我们的需求**，前提是：
1. **只使用底层工具**: `amk`, `alu`, `mov`, `label`, `assembler`, `disassembler`
2. **所有高层抽象在 xdsl 层**: 变量、延迟求值、控制流、优化
3. **OASM 定位明确**: 纯汇编器 - 指令编码 + 标签位置解析 + 机器码生成

❌ **不使用**:
- `expr` 延迟求值 → 用 xdsl SSA values
- 高层控制流 API → 用 xdsl qprog/rtmq dialects
- `table`/`context` 元编程 → 用 xdsl 类型系统

### 5.3 行动计划

#### Phase 3: 立即开始 (本周)

- [x] 评估 OASM 库（本文档）
- [ ] 实现 `RTMQEmitter` (使用底层 OASM 工具)
- [ ] 单元测试：指令生成
- [ ] 集成测试：简单 TTL pulse

#### Phase 4-5: 控制流 (后续)

- [ ] 在 xdsl qprog dialect 表示循环和分支
- [ ] Lowering 到 rtmq dialect（标签 + 跳转）
- [ ] `RTMQEmitter` 生成条件跳转汇编

#### 持续

- [ ] 完善测试覆盖率
- [ ] 回归测试：对比旧编译器
- [ ] 性能优化：减少冗余指令

---

## 6. 参考资料

- OASM 源码: `/home/tosaka/catseq/.venv/lib/python3.12/site-packages/oasm/`
- RTMQ ISA 文档: `~/.claude/skills/rtmq-mlir-compiler/references/isa.md`
- AST/MLIR 重构计划: `/home/tosaka/catseq/docs/AST_MLIR_REFACTOR_PLAN.md`
- xdsl 文档: https://xdsl.dev/

---

**文档版本**: 2.0 (修正版)
**创建日期**: 2026-01-05
**作者**: Claude (Sonnet 4.5)
**关键修正**: 明确 OASM 定位为纯汇编器后端，所有高层抽象在 xdsl 层实现
