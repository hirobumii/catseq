# OASM 设计文档技术审查报告

## 文档范围

本报告基于 RTMQ ISA 规范和 xdsl 0.55.4 API，审查以下两个文档的技术正确性：

1. `/home/tosaka/catseq/docs/OASM_LIBRARY_EVALUATION.md`
2. `/home/tosaka/catseq/docs/OASM_LINKING_DESIGN.md`

---

## 第一部分：RTMQ ISA 符合性审查

### 1.1 条件跳转机制 - ✅ 正确

**文档声明**（OASM_LIBRARY_EVALUATION.md）:
```python
# 条件跳转
amk('ptr', condition_reg, offset)  # 如果 condition_reg == -1 则跳转
```

**ISA 验证**（isa.md 第 124-126 行）:

PTR 是 Numeric CSR，AMK 指令的行为：
```
- If RD is a numeric CSR:
  - if R0[1:0] == 0b11 then RD = RD + R1  # 自增模式
  - else if R0[1:0] == 0b10 then RD = R1  # 直接赋值
  - else RD = RD                          # 无操作
```

**分析**:
- 当 `R0 = condition_reg` 且 `condition_reg == -1` (0xFFFFFFFF) 时：
  - `condition_reg[1:0] == 0b11` ✅
  - 触发自增：`PTR = PTR + offset` ✅
- 当 `condition_reg != -1` 时：
  - `condition_reg[1:0] != 0b11`（通常）
  - PTR 保持不变，继续顺序执行 ✅

**ISA 示例**（isa.md 第 385-389 行）:
```RTMQ
AMK P PTR $03 -10  % jump backward if $03 == -1
```

**结论**: ✅ **完全正确**。条件跳转机制符合 RTMQ ISA。

---

### 1.2 TCS 寄存器分配 - ⚠️ 需要澄清

**文档声明**（OASM_LINKING_DESIGN.md）:

```python
class RTMQCallingConvention:
    """寄存器分配:
      $00-$01    常量（0 和 -1）
      $02-$0F    临时寄存器（调用者保存）
      $10-$17    参数寄存器
      $18-$1F    返回值寄存器
      $20-$2F    保存寄存器（被调用者保存）
      $30-$FF    局部变量（栈分配）
    """
```

**ISA 规范**（isa.md 第 40-42 行）:

```
- The first 32 entries, $00 ~ $1F, serve as GPRs.
  They are always accessible, regardless of the stack pointer.
- The first 2 entries, $00 and $01, shall always be 0x00000000 and 0xFFFFFFFF.
- The physical addresses of entries $20 ~ $FF are offset with the stack pointer (STK CSR).
  For example, the physical address of $21 when STK == 0x5678 is 0x21 + 0x5678 == 0x5699.
```

**问题**:

1. **$00-$1F 是 GPRs**，始终可访问 ✅
   - $00 = 0，$01 = -1（硬件保证）✅
   - $02-$1F 可以自由分配 ✅

2. **$20-$FF 是栈相对寻址** ⚠️
   - 物理地址 = TCS 地址 + STK
   - 文档中 "$20-$2F 保存寄存器" 的说法**不够准确**
   - 应该说明：
     - $20-$FF 的**逻辑地址**固定
     - 但**物理地址**由 STK 决定
     - 函数调用时需要管理 STK

**建议修正**（OASM_LINKING_DESIGN.md）:

```python
class RTMQCallingConvention:
    """RTMQ 调用约定 v1

    寄存器分配:
      $00        - 常量 0（硬件保证）
      $01        - 常量 -1（硬件保证）
      $02-$0F    - 临时寄存器（调用者保存，GPR 区域）
      $10-$17    - 参数寄存器（最多 8 个参数，GPR 区域）
      $18-$1F    - 返回值寄存器（最多 8 个返回值，GPR 区域）
      $20-$FF    - 栈区域（物理地址 = $xx + STK）
                   - 被调用者通过调整 STK 分配局部变量
                   - 栈帧管理：caller 负责保存 STK，callee 负责恢复

    关键约束:
      - $00-$1F 是 GPRs，物理地址固定
      - $20-$FF 物理地址由 STK 偏移，需要栈管理
      - 函数调用前：保存当前 STK
      - 函数返回前：恢复 STK 到调用前的值
    """
```

**ISA 示例**（isa.md 第 492-507 行）:

```RTMQ
% 压栈示例
GLO - $20 0x1234
GLO - $21 0x5678
GLO - $22 0xABCD
AMK - STK 3.0 3   % advance the stack offset (STK += 3)

% 出栈示例
AMK P STK 3.0 -3  % reduce the stack offset (STK -= 3) and wait
CSR - $20 &AB
CSR - $21 &CD
CSR - $22 &EF
```

**结论**: ⚠️ **部分正确，需要澄清栈管理**。

---

### 1.3 AMK/ALU/MOV 指令使用 - ✅ 基本正确

**文档中的指令使用**（OASM_LIBRARY_EVALUATION.md）:

```python
# AMK 指令
amk('ttl', '2.0', '$01')  # 设置 TTL 位字段

# ALU 指令
alu('LST', '$10', '$20', '$21')  # $10 = ($20 < $21) ? -1 : 0

# MOV 指令
mov('$10', '$20')  # $10 = $20
```

**ISA 验证**:

1. **AMK 指令**（isa.md 第 118-173 行）:
   - ✅ `AMK - TTL 2.0 $01` 合法
   - Mask `2.0` = `2 << (0 * 2)` = 0x02（二进制 0b00000010）
   - 对 Flag CSR `TTL` 的位 1 执行掩码赋值

2. **ALU 指令**（isa.md 第 203-260 行）:
   - ✅ `LST - $10 $20 $21` 合法
   - LST (Less Than) 比较指令
   - 结果：$20 < $21 ? -1 : 0

3. **MOV 指令**:
   - ⚠️ ISA 中没有专门的 `MOV` 指令
   - 实际上 `MOV` 是 OASM 库的**宏**，会展开为：
     - `CSR - $rd $rs`（如果源是 CSR）
     - `ADD - $rd $rs $00`（如果源是 TCS，加 0）
     - `GLO - $rd imm`（如果源是立即数）

**建议补充说明**（OASM_LIBRARY_EVALUATION.md）:

```python
# MOV 是 OASM 宏，不是 RTMQ 原生指令
# 实际会展开为：
# - CSR 指令（CSR → TCS）
# - ADD 指令（TCS → TCS，加 0）
# - GLO 指令（立即数 → TCS）
```

**结论**: ✅ **基本正确，建议补充 MOV 是宏的说明**。

---

### 1.4 标签和跳转偏移计算 - ✅ 正确，⚠️ 有细节问题

**文档声明**（OASM_LIBRARY_EVALUATION.md）:

```python
def _compute_offset(self, target_label: str) -> int:
    """计算跳转偏移
    offset = target_position - current_position - 2
    （-2 是因为 PTR 跳转的基准是下下条指令）
    """
    target_pos = self.label_positions[target_label]
    offset = target_pos - self.current_pos - 2
    return offset
```

**ISA 规范**（isa.md 第 376-378 行）:

```
- Read value:
  - the address of the current instruction if it is from the instruction cache
  - the address of the last instruction from the instruction cache if on hold/paused
```

**分析**:

1. **PTR 读取值**：
   - 当前指令的地址

2. **跳转时的 PTR 值**：
   - 执行 `AMK P PTR $xx offset` 时
   - PTR 当前值 = 该 AMK 指令的地址
   - 自增后：`PTR_new = PTR_old + offset`
   - 实际跳转目标：`PTR_old + offset`

3. **偏移计算**：
   ```
   假设：
   - 当前 AMK 指令地址 = A
   - 目标地址 = T

   则：
   - PTR_old = A
   - PTR_new = A + offset = T
   - offset = T - A
   ```

**问题**:

文档中说 `-2` 是因为"下下条指令"，这个说法**不够准确**。

实际原因：
- `glo('$FE', offset)` - 占用 1 条指令位置
- `amk('ptr', '3.0', '$FE')` - 占用 1 条指令位置

假设 glo 在地址 100：
- glo 地址 = 100
- amk 地址 = 101
- PTR 在执行 amk 时 = 101
- 跳转后 PTR = 101 + offset

如果目标地址 = 200：
- offset = 200 - 101 = 99
- 但是代码中 current_pos 可能指向 glo（100）
- 所以 offset = 200 - 100 - 1 = 99 ✅

**更准确的说明**:

```python
def _compute_offset(self, target_label: str) -> int:
    """计算跳转偏移

    跳转指令序列：
      pos+0: glo('$FE', offset)       # 加载偏移到临时寄存器
      pos+1: amk('ptr', '3.0', '$FE') # 执行跳转

    当 amk 指令执行时：
      - PTR 当前值 = pos+1
      - PTR 新值 = (pos+1) + offset = target_pos
      - offset = target_pos - (pos+1)
             = target_pos - current_pos - 1

    但如果 current_pos 指向 glo 指令（pos+0）：
      - offset = target_pos - (current_pos+1)
             = target_pos - current_pos - 1
    """
    target_pos = self.label_positions[target_label]

    # 假设 current_pos 指向 glo 指令的位置
    # amk 指令在 current_pos + 1
    offset = target_pos - (self.current_pos + 1)

    # 更新 current_pos（两条指令）
    self.current_pos += 2

    return offset
```

**结论**: ✅ **计算正确，但说明需要更精确**。

---

### 1.5 函数调用序列 - ⚠️ 需要补充 LNK 处理

**文档声明**（OASM_LINKING_DESIGN.md）:

```python
"""调用序列:
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
"""
```

**ISA 规范**（isa.md 第 391-409 行）:

```
### LNK Register

LNK register stores the return address of the last jump.

- Read value:
  - the return address of the last jump
  - That is, any time when PTR is about to be written, LNK is updated with PTR + 1 first

Example: entry and return of a simple subroutine
CSR - $20 LNK      % save the return address
...
AMK P PTR 2.0 $20  % return
```

**关键发现**:

1. **LNK 自动更新** ✅
   - 任何时候写 PTR 之前，LNK 自动更新为 `PTR + 1`
   - 即返回地址 = 跳转指令的下一条指令

2. **调用序列简化**:
   ```RTMQ
   % 调用者
   GLO - $10 arg1        % 加载参数
   GLO - $11 arg2
   CLO P PTR #function   % 跳转（LNK 自动保存）

   % 被调用者
   #function:
   CSR - $20 LNK         % 可选：保存 LNK（如果会调用其他函数）
   ...                   % 函数体
   GLO - $18 result      % 返回值
   AMK P PTR 2.0 LNK     % 返回（直接用 LNK）
   ```

3. **文档中的 "MOV LNK" 是多余的** ⚠️
   - LNK 在跳转时自动保存
   - 调用者**不需要**手动保存 LNK
   - 但被调用者如果要再调用其他函数，需要先保存 LNK

**建议修正**（OASM_LINKING_DESIGN.md）:

```python
"""RTMQ 调用序列

硬件自动行为:
  - 任何写 PTR 之前，LNK 自动更新为 PTR + 1
  - 因此调用者不需要手动保存返回地址

调用序列:
  1. 调用者: 加载参数到 $10-$17
  2. 调用者: 保存需要的临时寄存器 ($02-$0F)
  3. 调用者: 跳转到函数 (CLO P PTR #function)
               ↑ LNK 自动保存为跳转指令的下一条地址
  4. 被调用者: （可选）保存 LNK（如果会调用其他函数）
  5. 被调用者: 保存 STK 和需要的寄存器
  6. 被调用者: 执行函数体
  7. 被调用者: 加载返回值到 $18-$1F
  8. 被调用者: 恢复 STK 和寄存器
  9. 被调用者: （可选）恢复 LNK（如果之前保存了）
  10. 被调用者: 返回 (AMK P PTR 2.0 LNK)
  11. 调用者: 恢复临时寄存器
  12. 调用者: 读取返回值

RTMQ 汇编示例:
  % 调用者
  GLO - $10 arg1
  GLO - $11 arg2
  CLO P PTR #my_function  % LNK 自动保存

  % 被调用者
  #my_function:
  CSR - $20 LNK          % 保存 LNK（如果会调用其他函数）
  CSR - $21 STK          % 保存 STK
  AMK - STK 3.0 10       % 分配 10 个栈槽

  % ... 函数体 ...

  GLO - $18 result       % 返回值
  AMK - STK 3.0 -10      % 释放栈空间
  MOV - STK $21          % 恢复 STK
  MOV - LNK $20          % 恢复 LNK（如果保存了）
  AMK P PTR 2.0 LNK      % 返回
"""
```

**结论**: ⚠️ **需要补充 LNK 自动保存机制的说明**。

---

### 1.6 时间语义 - ✅ 正确

**文档声明**（OASM_LINKING_DESIGN.md）:

```python
# 确定时长
InlineAsm(code="...", duration_cycles=2500)

# 编译器处理:
total_duration += func.duration_cycles
```

**ISA 背景**:

RTMQ 是 cycle-accurate 架构：
- 每条指令执行时间确定（通常 1 cycle）
- 用户可以精确控制时序

**分析**:

1. **内联汇编声明时长** ✅
   - 用户必须手动声明精确时长
   - 编译器信任这个声明

2. **时长验证** ⚠️
   - 文档中缺少**验证机制**
   - 建议：编译器应该静态分析 OASM 代码，验证声明的时长是否正确

**建议补充**:

```python
class InlineAsm:
    def verify_duration(self) -> bool:
        """验证声明的时长是否正确"""
        actual_cycles = 0
        for instr in self.instructions:
            actual_cycles += self._get_instruction_cycles(instr)

        if actual_cycles != self.duration_cycles:
            raise ValueError(
                f"Duration mismatch: declared {self.duration_cycles}, "
                f"actual {actual_cycles}"
            )
        return True

    def _get_instruction_cycles(self, instr) -> int:
        """获取指令的执行周期数"""
        # 大多数指令 = 1 cycle
        # wait_mu(N) = N cycles
        # NOP H = 不确定（等待外部事件）
        if instr.opcode == 'WAIT':
            return instr.operands[0]
        elif instr.opcode == 'NOP' and instr.flag == 'H':
            raise ValueError("Cannot statically determine duration with NOP H")
        else:
            return 1
```

**结论**: ✅ **概念正确，建议增加验证机制**。

---

## 第二部分：xdsl 0.55.4 符合性审查

### 2.1 Dialect 定义 - ⚠️ 需要修正

**文档声明**（OASM_LIBRARY_EVALUATION.md）:

```python
@irdl_op_definition
class RTMQ_AMK_Op(IRDLOperation):
    name = "rtmq.amk"
    csr = operand_def(CSRType)
    mask = operand_def(MaskType)
    value = operand_def(TCSRegisterType)
    result = result_def(TCSRegisterType)
```

**xdsl 0.55.4 API 问题**:

1. **Operand 应该是 SSA values，不是类型** ❌
   ```python
   # ❌ 错误
   csr = operand_def(CSRType)

   # ✅ 正确
   from xdsl.irdl import Attribute
   csr = operand_def(Attribute)  # Operand 是 SSAValue，类型在运行时检查
   ```

2. **属性（Attributes）应该用 `attr_def`** ⚠️
   ```python
   # CSR 名称和 mask 是编译时常量，应该是属性
   csr_name = attr_def(StringAttr)
   mask_pattern = attr_def(StringAttr)
   ```

**正确的实现**:

```python
from xdsl.ir import Attribute, Data
from xdsl.irdl import (
    irdl_op_definition, irdl_attr_definition,
    IRDLOperation, ParametrizedAttribute,
    operand_def, attr_def, result_def, ParameterDef,
    AnyAttr
)
from xdsl.dialects.builtin import StringAttr, IntAttr

# 定义 TCS 寄存器类型
@irdl_attr_definition
class TCSRegisterType(ParametrizedAttribute):
    name = "rtmq.tcs_register"
    reg_id: ParameterDef[IntAttr]  # 寄存器 ID ($00-$FF)

# 定义 CSR 类型
@irdl_attr_definition
class CSRType(ParametrizedAttribute):
    name = "rtmq.csr"
    csr_name: ParameterDef[StringAttr]  # CSR 名称或地址

# AMK 操作定义
@irdl_op_definition
class RTMQ_AMK_Op(IRDLOperation):
    name = "rtmq.amk"

    # Operands（SSA values）
    value = operand_def(AnyAttr())  # 可以是 TCS 寄存器值或立即数

    # Attributes（编译时常量）
    csr = attr_def(StringAttr)  # CSR 名称（如 "ttl", "ptr"）
    mask = attr_def(StringAttr)  # Mask 模式（如 "2.0", "3.0"）

    # Assembly format
    assembly_format = (
        "$csr `,` $mask `,` $value attr-dict `:` type($value)"
    )

    def verify_(self) -> None:
        """验证操作的合法性"""
        # 验证 CSR 名称
        valid_csrs = ["ptr", "lnk", "stk", "ttl", "rwg", ...]
        if self.csr.data not in valid_csrs:
            # 检查是否是 &xx 格式
            if not self.csr.data.startswith('&'):
                raise VerifyException(f"Invalid CSR: {self.csr.data}")

        # 验证 mask 格式
        if not self._is_valid_mask(self.mask.data):
            raise VerifyException(f"Invalid mask: {self.mask.data}")

    @staticmethod
    def _is_valid_mask(mask: str) -> bool:
        """验证 mask 是否符合 X.P 格式"""
        parts = mask.split('.')
        if len(parts) != 2:
            return False
        try:
            x = int(parts[0], 16)
            p = int(parts[1], 16)
            return 0 <= x < 16 and 0 <= p < 16
        except ValueError:
            return False
```

**使用示例**:

```python
from xdsl.builder import Builder, ImplicitBuilder
from xdsl.ir import Block, Region

# 创建 AMK 操作
@Builder.implicit_region
def build_ttl_on(arg: BlockArgument) -> None:
    # arg 是 TCS 寄存器值（SSA value）
    amk_op = RTMQ_AMK_Op.create(
        operands=[arg],  # SSA value
        attributes={
            "csr": StringAttr("ttl"),
            "mask": StringAttr("2.0"),
        },
    )
    yield amk_op

# 使用 Builder
builder = Builder()
block = Block(arg_types=[TCSRegisterType(IntAttr(1))])

with ImplicitBuilder(builder):
    ttl_value = block.args[0]
    amk_op = RTMQ_AMK_Op.create(
        operands=[ttl_value],
        attributes={
            "csr": StringAttr("ttl"),
            "mask": StringAttr("2.0"),
        },
    )
    builder.insert(amk_op)
```

**结论**: ⚠️ **需要重大修正，当前设计不符合 xdsl API**。

---

### 2.2 SSA Values 和寄存器映射 - ⚠️ 需要改进

**文档声明**（OASM_LIBRARY_EVALUATION.md）:

```python
def _get_tcs_register(self, value: SSAValue) -> str:
    """获取 SSA value 分配的 TCS 寄存器"""
    reg_attr = value.attributes.get('tcs_register')
    reg_id = reg_attr.reg_id.data
    return f"${reg_id:02X}"
```

**问题**:

1. **SSAValue 没有 `attributes` 字段** ❌
   - xdsl 中，SSAValue 只有 `type`和`uses`
   - 属性应该附加到**定义该值的 Operation** 上

2. **寄存器分配应该是单独的 Pass** ⚠️
   - 不应该在 CodeGen 时查询
   - 应该在 Lowering 阶段完成

**正确的实现**:

```python
from xdsl.passes import ModulePass
from xdsl.ir import Operation, SSAValue
from xdsl.dialects.builtin import IntAttr

class TCSRegisterAllocationPass(ModulePass):
    """TCS 寄存器分配 Pass"""

    name = "rtmq-register-allocation"

    def apply(self, ctx: MLContext, module: ModuleOp) -> None:
        """分配 TCS 寄存器"""
        allocator = TCSAllocator()

        # 遍历所有 Operation
        for op in module.walk():
            # 为每个 SSA value 分配寄存器
            for result in op.results:
                if not self._has_register(op):
                    reg_id = allocator.allocate()
                    # 将寄存器 ID 存储在 Operation 的属性中
                    op.attributes["tcs_reg"] = IntAttr(reg_id)

    def _has_register(self, op: Operation) -> bool:
        """检查 Operation 是否已分配寄存器"""
        return "tcs_reg" in op.attributes

class TCSAllocator:
    """TCS 寄存器分配器"""

    def __init__(self):
        # GPR 区域: $00-$1F
        # 栈区域: $20-$FF
        # 我们从 $30 开始分配（避开调用约定保留的寄存器）
        self.next_reg = 0x30
        self.allocated = set()

    def allocate(self) -> int:
        """分配一个新的 TCS 寄存器"""
        if self.next_reg > 0xFF:
            raise RuntimeError("TCS registers exhausted")

        reg_id = self.next_reg
        self.allocated.add(reg_id)
        self.next_reg += 1
        return reg_id

    def free(self, reg_id: int) -> None:
        """释放寄存器（用于寄存器复用优化）"""
        self.allocated.remove(reg_id)

# CodeGen 时查询寄存器分配
class RTMQEmitter:
    def _get_tcs_register(self, value: SSAValue) -> str:
        """获取 SSA value 的 TCS 寄存器"""
        # 找到定义该 value 的 Operation
        defining_op = value.owner

        # 从 Operation 的属性中获取寄存器分配
        if "tcs_reg" not in defining_op.attributes:
            raise ValueError(f"SSA value {value} not allocated to register")

        reg_id = defining_op.attributes["tcs_reg"].data
        return f"${reg_id:02X}"
```

**使用流程**:

```python
# 1. 构建 MLIR IR
module = build_catseq_ir()

# 2. Lowering passes
lowering_passes = [
    CatSeqToQProgPass(),
    QProgToQCtrlPass(),
    QCtrlToRTMQPass(),
]
for pass_ in lowering_passes:
    pass_.apply(ctx, module)

# 3. 寄存器分配
allocation_pass = TCSRegisterAllocationPass()
allocation_pass.apply(ctx, module)

# 4. 代码生成
emitter = RTMQEmitter(module)
oasm_code = emitter.emit()
```

**结论**: ⚠️ **需要改进，应使用标准的 Pass 架构**。

---

### 2.3 Region 和 Block 使用 - ✅ 基本正确

**文档声明**（OASM_LIBRARY_EVALUATION.md）:

```python
@irdl_op_definition
class RTMQ_Function_Op(IRDLOperation):
    name = "rtmq.function"
    body = region_def()
```

**xdsl 验证**: ✅ 正确

- `region_def()` 定义一个 Region
- Region 包含多个 Block
- Block 包含多个 Operation

**改进建议**:

```python
from xdsl.irdl import region_def, attr_def
from xdsl.dialects.builtin import StringAttr, ArrayAttr

@irdl_op_definition
class RTMQ_Function_Op(IRDLOperation):
    name = "rtmq.function"

    # 函数名
    sym_name = attr_def(StringAttr)

    # 函数签名（参数和返回值类型）
    function_type = attr_def(FunctionType)

    # 函数体（单个 Region，可能多个 Block）
    body = region_def()

    # Assembly format
    assembly_format = (
        "$sym_name `(` `)` attr-dict-with-keyword $body "
        "`:` $function_type"
    )

    def verify_(self) -> None:
        """验证函数定义"""
        # Region 必须非空
        if len(self.body.blocks) == 0:
            raise VerifyException("Function body cannot be empty")

        # 第一个 Block 是入口块
        entry_block = self.body.blocks[0]

        # 入口块的参数类型必须匹配函数签名
        func_type = self.function_type
        if len(entry_block.args) != len(func_type.inputs):
            raise VerifyException(
                f"Entry block has {len(entry_block.args)} args, "
                f"but function type expects {len(func_type.inputs)}"
            )
```

**使用示例**:

```python
# 构建函数
@Builder.implicit_region
def build_function(arg0: BlockArgument, arg1: BlockArgument):
    # arg0, arg1 是函数参数（SSA values）
    result = RTMQ_AMK_Op.create(...)
    return_op = RTMQ_Return_Op.create(operands=[result])

# 创建 Function Operation
func_op = RTMQ_Function_Op.create(
    attributes={
        "sym_name": StringAttr("my_function"),
        "function_type": FunctionType.from_lists(
            [TCSRegisterType(), TCSRegisterType()],  # 参数类型
            [TCSRegisterType()],  # 返回值类型
        ),
    },
    regions=[build_function_region()],
)
```

**结论**: ✅ **基本正确，建议增加验证逻辑**。

---

### 2.4 Lowering Passes 设计 - ✅ 可行，⚠️ 需要细化

**文档声明**（AST_MLIR_REFACTOR_PLAN.md）:

```
catseq dialect → qprog dialect → qctrl dialect → rtmq dialect
```

**xdsl 实现**:

```python
from xdsl.pattern_rewriter import (
    RewritePattern,
    PatternRewriter,
    op_type_rewrite_pattern,
    GreedyRewritePatternApplier,
)

class LowerCatSeqComposToQCtrl(RewritePattern):
    """Lowering: catseq.compos → qctrl 操作序列"""

    @op_type_rewrite_pattern
    def match_and_rewrite(
        self, op: CatSeq_Compos_Op, rewriter: PatternRewriter
    ):
        # 获取左右操作数
        lhs_morphism = op.lhs
        rhs_morphism = op.rhs

        # Lower 为 qctrl 序列
        # 1. 计算时间对齐
        lhs_duration = self._get_duration(lhs_morphism)
        rhs_duration = self._get_duration(rhs_morphism)

        # 2. 生成 qctrl 操作
        qctrl_ops = []

        # lhs 的操作
        qctrl_ops.extend(self._lower_morphism(lhs_morphism))

        # rhs 的操作（时间偏移 = lhs_duration）
        rhs_ops = self._lower_morphism(rhs_morphism)
        for rhs_op in rhs_ops:
            # 调整时间戳
            rhs_op.attributes["timestamp"] = IntAttr(
                rhs_op.attributes["timestamp"].data + lhs_duration
            )
        qctrl_ops.extend(rhs_ops)

        # 3. 替换原操作
        rewriter.replace_matched_op(qctrl_ops)

class LowerQProgForToRTMQ(RewritePattern):
    """Lowering: qprog.for → rtmq 循环（标签 + 跳转）"""

    @op_type_rewrite_pattern
    def match_and_rewrite(
        self, op: QProg_For_Op, rewriter: PatternRewriter
    ):
        """
        qprog.for %count {
          ^body(%i: i32):
            ...
            qprog.yield
        }

        →

        rtmq.label "loop_start"
        rtmq.load_imm %counter, 0
        rtmq.label "loop_body"
        ...  # 循环体
        rtmq.alu "ADD", %counter, %counter, 1
        rtmq.alu "LST", %cond, %counter, %count
        rtmq.branch %cond, ^loop_body, ^loop_end
        rtmq.label "loop_end"
        """

        # 生成唯一标签
        loop_id = self._fresh_label_id()
        loop_start = f"__loop_start_{loop_id}"
        loop_body = f"__loop_body_{loop_id}"
        loop_end = f"__loop_end_{loop_id}"

        # 生成 RTMQ 操作
        new_ops = [
            RTMQ_Label_Op.create(attributes={"label": StringAttr(loop_start)}),
            RTMQ_LoadImm_Op.create(...),  # 初始化计数器
            RTMQ_Label_Op.create(attributes={"label": StringAttr(loop_body)}),
            # ... 循环体 ...
            RTMQ_ALU_Op.create(...),  # 自增
            RTMQ_ALU_Op.create(...),  # 比较
            RTMQ_Branch_Op.create(...),  # 条件跳转
            RTMQ_Label_Op.create(attributes={"label": StringAttr(loop_end)}),
        ]

        rewriter.replace_matched_op(new_ops)

# 应用 Passes
def apply_lowering_passes(module: ModuleOp):
    """应用所有 Lowering passes"""

    # Pass 1: catseq → qctrl
    patterns_1 = [
        LowerCatSeqComposToQCtrl(),
        LowerCatSeqTensorToQCtrl(),
        # ... 其他模式
    ]
    applier_1 = GreedyRewritePatternApplier(patterns_1)
    applier_1.rewrite_module(module)

    # Pass 2: qprog → rtmq（控制流）
    patterns_2 = [
        LowerQProgForToRTMQ(),
        LowerQProgIfToRTMQ(),
        # ...
    ]
    applier_2 = GreedyRewritePatternApplier(patterns_2)
    applier_2.rewrite_module(module)

    # Pass 3: qctrl → rtmq（硬件操作）
    patterns_3 = [
        LowerQCtrlTTLToRTMQ(),
        LowerQCtrlWaitToRTMQ(),
        # ...
    ]
    applier_3 = GreedyRewritePatternApplier(patterns_3)
    applier_3.rewrite_module(module)

    return module
```

**结论**: ✅ **设计可行，需要具体实现每个 Pattern**。

---

## 第三部分：改进建议总结

### 3.1 高优先级修正

1. **修正 xdsl Dialect 定义** ⚠️
   - Operands 使用 `operand_def(AnyAttr())`
   - Attributes 使用 `attr_def(StringAttr)` 等
   - 添加 `verify_()` 方法

2. **澄清 TCS 栈管理** ⚠️
   - 明确 $20-$FF 是栈相对寻址
   - 补充 STK 管理说明
   - 更新调用约定

3. **补充 LNK 自动保存机制** ⚠️
   - 删除 "MOV LNK" 的错误说法
   - 说明 LNK 硬件自动更新

4. **实现寄存器分配 Pass** ⚠️
   - 创建独立的 `TCSRegisterAllocationPass`
   - 寄存器信息存储在 Operation 属性中
   - CodeGen 时查询属性

### 3.2 中优先级改进

5. **增加时长验证机制** ⚠️
   - 内联汇编自动验证时长
   - 静态分析指令周期数

6. **精确化跳转偏移说明** ⚠️
   - 明确 PTR 当前值的含义
   - 解释 -1 或 -2 的具体原因

7. **补充 MOV 是宏的说明** ⚠️
   - MOV 不是 RTMQ 原生指令
   - 展开为 CSR/ADD/GLO

### 3.3 低优先级优化

8. **完善 Dialect 验证逻辑**
   - 检查 CSR 名称合法性
   - 验证 mask 格式
   - 检查寄存器范围

9. **优化 Lowering Pattern**
   - 增加更多优化 Pass
   - 死代码消除
   - 常量折叠

10. **改进错误信息**
    - 更清晰的编译错误提示
    - 源码位置映射

---

## 第四部分：具体代码修正示例

### 示例 1: 修正 RTMQ Dialect 定义

**文件**: `catseq/mlir/dialects/rtmq.py`

```python
from xdsl.ir import Dialect
from xdsl.irdl import (
    irdl_op_definition,
    irdl_attr_definition,
    IRDLOperation,
    ParametrizedAttribute,
    operand_def,
    attr_def,
    result_def,
    region_def,
    ParameterDef,
    AnyAttr,
)
from xdsl.dialects.builtin import StringAttr, IntAttr, ArrayAttr

# ========== Attributes ==========

@irdl_attr_definition
class TCSRegisterType(ParametrizedAttribute):
    """TCS 寄存器类型"""
    name = "rtmq.tcs_register"
    reg_id: ParameterDef[IntAttr]  # 寄存器 ID ($00-$FF)

@irdl_attr_definition
class CSRNameAttr(ParametrizedAttribute):
    """CSR 名称属性"""
    name = "rtmq.csr_name"
    csr_name: ParameterDef[StringAttr]  # CSR 名称或 &xx

# ========== Operations ==========

@irdl_op_definition
class RTMQ_AMK_Op(IRDLOperation):
    """AMK 指令：掩码赋值

    语法: rtmq.amk "ttl", "2.0", %value : !rtmq.tcs_register

    例子:
      %ttl_val = rtmq.load_imm 1 : !rtmq.tcs_register
      rtmq.amk "ttl", "2.0", %ttl_val : !rtmq.tcs_register
    """
    name = "rtmq.amk"

    # Operands (SSA values)
    value = operand_def(AnyAttr())

    # Attributes (编译时常量)
    csr = attr_def(StringAttr)
    mask = attr_def(StringAttr)

    # Assembly format
    assembly_format = "$csr `,` $mask `,` $value attr-dict `:` type($value)"

    def verify_(self) -> None:
        # 验证 mask 格式
        if not self._is_valid_mask(self.mask.data):
            raise VerifyException(f"Invalid mask format: {self.mask.data}")

    @staticmethod
    def _is_valid_mask(mask: str) -> bool:
        parts = mask.split('.')
        if len(parts) != 2:
            return False
        try:
            x, p = int(parts[0], 16), int(parts[1], 16)
            return 0 <= x < 16 and 0 <= p < 16
        except ValueError:
            return False

@irdl_op_definition
class RTMQ_Branch_Op(IRDLOperation):
    """条件分支指令

    语法: rtmq.branch %cond, ^then, ^else
    """
    name = "rtmq.branch"

    condition = operand_def(TCSRegisterType)
    then_target = attr_def(StringAttr)  # 标签名
    else_target = attr_def(StringAttr)

    assembly_format = (
        "$condition `,` $then_target `,` $else_target "
        "attr-dict `:` type($condition)"
    )

# ========== Dialect ==========

RTMQ = Dialect(
    "rtmq",
    [
        RTMQ_AMK_Op,
        RTMQ_Branch_Op,
        # ... 其他操作
    ],
    [
        TCSRegisterType,
        CSRNameAttr,
    ],
)
```

### 示例 2: 修正调用约定文档

**文件**: `catseq/docs/OASM_LINKING_DESIGN.md`

```markdown
## 4.2 调用约定（修正版）

### RTMQ 调用约定 v1.1

#### 寄存器分配

根据 RTMQ ISA（isa.md 第 40-42 行）：

- **GPR 区域** ($00-$1F，物理地址固定)：
  - $00：硬件常量 0
  - $01：硬件常量 -1 (0xFFFFFFFF)
  - $02-$0F：临时寄存器（调用者保存）
  - $10-$17：参数寄存器（最多 8 个参数）
  - $18-$1F：返回值寄存器（最多 8 个返回值）

- **栈区域** ($20-$FF，物理地址 = $xx + STK)：
  - 局部变量由被调用者通过调整 STK 分配
  - 每个函数拥有独立的栈帧

#### 调用序列（利用 LNK 自动保存）

根据 RTMQ ISA（isa.md 第 397-399 行）：
> Any time when PTR is about to be written, LNK is updated with PTR + 1 first

因此，调用者**不需要**手动保存返回地址。

**完整调用序列**：

1. **调用者 - 准备调用**：
   ```RTMQ
   GLO - $10 arg1        % 加载参数到 $10-$17
   GLO - $11 arg2
   CSR - $30 STK         % 可选：保存 STK（如果调用者使用栈）
   CLO P PTR #my_func    % 跳转，LNK 自动保存为下一条指令地址
   ```

2. **被调用者 - 函数入口**：
   ```RTMQ
   #my_func:
   CSR - $20 LNK         % 保存 LNK（仅当需要调用其他函数时）
   CSR - $21 STK         % 保存 STK
   AMK - STK 3.0 10      % 分配 10 个栈槽（STK += 10）
   ```

3. **被调用者 - 函数体**：
   ```RTMQ
   % 使用 $20-$2F 作为局部变量（栈相对寻址）
   GLO - $20 local1
   GLO - $21 local2
   % ... 函数逻辑 ...
   ```

4. **被调用者 - 函数返回**：
   ```RTMQ
   GLO - $18 result      % 返回值到 $18-$1F
   AMK - STK 3.0 -10     % 释放栈空间（STK -= 10）
   MOV - STK $21         % 恢复 STK
   MOV - LNK $20         % 恢复 LNK（如果保存了）
   AMK P PTR 2.0 LNK     % 返回（直接用 LNK）
   ```

5. **调用者 - 调用后**：
   ```RTMQ
   % 自动返回到这里
   MOV - STK $30         % 可选：恢复 STK
   CSR - $30 $18         % 读取返回值
   ```

#### 关键约束

1. **LNK 的管理**：
   - 叶子函数（不调用其他函数）：无需保存 LNK
   - 非叶子函数：必须保存/恢复 LNK

2. **STK 的管理**：
   - 被调用者负责：保存 STK → 分配栈空间 → 释放栈空间 → 恢复 STK
   - 调用者不需要管理 STK（除非自己也使用栈）

3. **寄存器生命周期**：
   - GPR ($00-$1F)：全局可见，物理地址不变
   - 栈区域 ($20-$FF)：局部可见，物理地址 = $xx + STK
```

---

## 总结

### 技术正确性评分

| 方面 | 评分 | 说明 |
|------|------|------|
| **RTMQ ISA 符合性** | ⭐⭐⭐⭐ | 基本正确，需要澄清栈管理和 LNK |
| **xdsl API 符合性** | ⭐⭐⭐ | 需要重大修正（Dialect 定义） |
| **整体架构设计** | ⭐⭐⭐⭐⭐ | 设计理念正确，分层清晰 |
| **实现可行性** | ⭐⭐⭐⭐ | 可行，需要补充细节 |

### 必须修正的问题

1. **xdsl Dialect 定义**：Operands vs Attributes
2. **TCS 栈管理**：明确 $20-$FF 的栈相对寻址
3. **LNK 自动保存**：删除错误的 "MOV LNK" 说法
4. **寄存器分配 Pass**：实现标准的 Pass 架构

### 建议的下一步

1. 根据本报告修正两个文档
2. 实现正确的 xdsl Dialect 定义
3. 编写单元测试验证每个技术点
4. 创建最小可行示例（端到端编译）

---

**报告版本**: 1.0
**审查日期**: 2026-01-05
**审查者**: Claude (Sonnet 4.5) with RTMQ ISA + xdsl 0.55.4 skills
**状态**: 完成，待用户确认修正
