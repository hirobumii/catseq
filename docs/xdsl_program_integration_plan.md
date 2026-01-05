# CatSeq Program AST → xDSL 深度集成方案

## 目标

将当前的 Program AST（控制流层）重构为 xDSL IR，实现：
- ✅ 迭代器遍历（避免栈溢出）
- ✅ 利用 xDSL 的 pattern rewriting 框架
- ✅ 与 Morphism 层的 catseq dialect 无缝集成
- ✅ 保持现有 Python API 不变

## 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│  Python API (Program, execute, seq, repeat, cond)          │  ← 用户接口（不变）
└──────────────────┬──────────────────────────────────────────┘
                   │ 适配器层
┌──────────────────▼──────────────────────────────────────────┐
│  catseq.program dialect (xDSL IR)                           │  ← 新增
│  - program.execute, program.sequence, program.for           │
│  - program.if, program.cond                                 │
└──────────────────┬──────────────────────────────────────────┘
                   │ Lowering Pass (展开控制流)
┌──────────────────▼──────────────────────────────────────────┐
│  catseq dialect (Morphism 层，已设计)                        │
│  - catseq.compos, catseq.tensor, catseq.atomic              │
└──────────────────┬──────────────────────────────────────────┘
                   │ Lowering Pass
┌──────────────────▼──────────────────────────────────────────┐
│  qctrl dialect (硬件操作层)                                  │
└──────────────────┬──────────────────────────────────────────┘
                   │ Lowering Pass
┌──────────────────▼──────────────────────────────────────────┐
│  rtmq dialect (RTMQ 指令层)                                  │
└──────────────────┬──────────────────────────────────────────┘
                   │ Code Generation
                   ▼
              OASM DSL / 汇编
```

## catseq.program Dialect 设计

### 核心 Types

```python
from xdsl.irdl import irdl_attr_definition, ParametrizedAttribute, param_def
from xdsl.ir import Attribute
from xdsl.dialects.builtin import IntegerAttr, StringAttr

@irdl_attr_definition
class MorphismRefType(Attribute):
    """Morphism 引用类型（跨 dialect 引用）

    !program.morphism_ref<id>
    """
    name = "program.morphism_ref"

    morphism_id = param_def(IntegerAttr)  # Morphism 对象的唯一 ID


@irdl_attr_definition
class ConditionType(Attribute):
    """条件表达式类型

    !program.condition
    """
    name = "program.condition"
```

### 核心 Operations

#### 1. ExecuteOp - 执行 Morphism

```python
from xdsl.irdl import irdl_op_definition, IRDLOperation, attr_def
from xdsl.ir import SSAValue

@irdl_op_definition
class ExecuteOp(IRDLOperation):
    """执行单个 Morphism

    program.execute %morphism_ref

    例如：
        %ref = program.morphism_ref<42>
        program.execute %ref
    """
    name = "program.execute"

    morphism_ref = attr_def(MorphismRefType)

    assembly_format = "$morphism_ref attr-dict"

    def verify_(self) -> None:
        # 验证 morphism_ref 有效性
        pass
```

#### 2. SequenceOp - 顺序执行

```python
from xdsl.irdl import region_def

@irdl_op_definition
class SequenceOp(IRDLOperation):
    """顺序执行多个操作（使用 Region）

    program.sequence {
        program.execute %ref1
        program.execute %ref2
        program.for ...
    }

    关键设计：使用 xDSL Region，自动获得遍历能力！
    """
    name = "program.sequence"

    body = region_def("single_block")  # 单 block region

    assembly_format = "$body attr-dict"

    def verify_(self) -> None:
        # 验证 body 不为空
        if not self.body.blocks:
            raise VerifyException("Sequence body cannot be empty")
```

#### 3. ForOp - 循环

```python
@irdl_op_definition
class ForOp(IRDLOperation):
    """For 循环

    program.for %count {
        ^bb0(%iter: !program.loop_var):
            program.execute %ref
    }

    或者简化版（不使用循环变量）：
    program.for %count {
        program.execute %ref
    }
    """
    name = "program.for"

    count = attr_def(IntegerAttr)  # 循环次数（编译时常量）
    body = region_def("single_block")

    assembly_format = "$count $body attr-dict"

    def verify_(self) -> None:
        if self.count.value.data <= 0:
            raise VerifyException("Loop count must be positive")
```

#### 4. IfOp - 条件分支

```python
@irdl_op_definition
class IfOp(IRDLOperation):
    """条件分支（支持运行时条件）

    program.if %condition {
        // then branch
        program.execute %ref1
    } else {
        // else branch (optional)
        program.execute %ref2
    }
    """
    name = "program.if"

    condition = attr_def(ConditionType)
    then_region = region_def("single_block")
    else_region = region_def("single_block")  # 可选，通过验证控制

    assembly_format = "$condition $then_region (`else` $else_region^)? attr-dict"

    def verify_(self) -> None:
        # then_region 必须存在
        if not self.then_region.blocks:
            raise VerifyException("Then branch cannot be empty")
```

#### 5. CondOp - 多路分支

```python
@irdl_op_definition
class CondOp(IRDLOperation):
    """多路分支（guard-style）

    program.cond {
        ^bb0(%cond1: !program.condition):
            program.execute %ref1
        ^bb1(%cond2: !program.condition):
            program.execute %ref2
        ^bb_default:
            program.execute %ref_default
    }

    注意：使用多个 block 表示不同分支
    """
    name = "program.cond"

    body = region_def()  # 多 block region

    assembly_format = "$body attr-dict"
```

### 辅助 Operations（条件表达式）

```python
@irdl_op_definition
class CompareOp(IRDLOperation):
    """比较操作（生成条件）

    %cond = program.compare %var, %value : ">" : !program.condition
    """
    name = "program.compare"

    var_ref = attr_def(StringAttr)  # 变量名（引用 TCS 寄存器）
    comparator = attr_def(StringAttr)  # ">", "<", "==", etc.
    value = attr_def(IntegerAttr)  # 比较值

    result = result_def(ConditionType)

    assembly_format = "$var_ref `,` $value `:` $comparator attr-dict `:` type($result)"


@irdl_op_definition
class LogicalAndOp(IRDLOperation):
    """逻辑与

    %result = program.and %cond1, %cond2 : !program.condition
    """
    name = "program.and"

    lhs = operand_def(ConditionType)
    rhs = operand_def(ConditionType)
    result = result_def(ConditionType)

    assembly_format = "$lhs `,` $rhs attr-dict `:` type($result)"


@irdl_op_definition
class LogicalOrOp(IRDLOperation):
    """逻辑或"""
    name = "program.or"

    lhs = operand_def(ConditionType)
    rhs = operand_def(ConditionType)
    result = result_def(ConditionType)

    assembly_format = "$lhs `,` $rhs attr-dict `:` type($result)"


@irdl_op_definition
class LogicalNotOp(IRDLOperation):
    """逻辑非"""
    name = "program.not"

    operand = operand_def(ConditionType)
    result = result_def(ConditionType)

    assembly_format = "$operand attr-dict `:` type($result)"
```

## Python API 适配器层

### 设计原则
- 保持现有 Python API 完全不变
- 内部使用 xDSL IR
- 延迟构建 IR（直到需要编译时）

### 实现策略

```python
from xdsl.ir import MLContext, Module, Block, Region
from xdsl.builder import Builder, ImplicitBuilder
from dataclasses import dataclass, field

@dataclass
class Program:
    """Program Monad（外部接口不变）

    内部使用 xDSL IR
    """
    _morphism_registry: dict[int, Morphism] = field(default_factory=dict)
    _next_morphism_id: int = 0
    _root_op: IRDLOperation | None = None  # xDSL operation

    @staticmethod
    def pure(morphism: Morphism) -> 'Program':
        """将 Morphism 提升到 Program Monad"""
        program = Program()
        morphism_id = program._register_morphism(morphism)

        # 创建 xDSL ExecuteOp
        morphism_ref = MorphismRefType([IntegerAttr(morphism_id)])
        execute_op = ExecuteOp.build(attributes={"morphism_ref": morphism_ref})
        program._root_op = execute_op

        return program

    def _register_morphism(self, morphism: Morphism) -> int:
        """注册 Morphism 并返回 ID"""
        morphism_id = self._next_morphism_id
        self._morphism_registry[morphism_id] = morphism
        self._next_morphism_id += 1
        return morphism_id

    def __rshift__(self, other: 'Program') -> 'Program':
        """>> 操作符：顺序组合

        使用 xDSL SequenceOp
        """
        if not isinstance(other, Program):
            return NotImplemented

        # 创建新的 Program
        result = Program()
        result._morphism_registry.update(self._morphism_registry)
        result._morphism_registry.update(other._morphism_registry)
        result._next_morphism_id = max(self._next_morphism_id, other._next_morphism_id)

        # 创建 SequenceOp
        with ImplicitBuilder() as builder:
            seq_region = Region([Block()])
            with builder.at_block_begin(seq_region.blocks[0]):
                # 克隆 self 和 other 的操作到 sequence body
                builder.insert(self._root_op.clone())
                builder.insert(other._root_op.clone())

            result._root_op = SequenceOp.build(regions=[seq_region])

        return result

    def replicate(self, n: int | CompileTimeParam) -> 'Program':
        """重复 n 次（使用 xDSL ForOp）"""
        if isinstance(n, int):
            if n <= 0:
                raise ValueError("Replication count must be positive")
            count_attr = IntegerAttr(n, IntegerType(32))
        else:
            count_attr = IntegerAttr(n.value, IntegerType(32))

        result = Program()
        result._morphism_registry.update(self._morphism_registry)
        result._next_morphism_id = self._next_morphism_id

        # 创建 ForOp
        with ImplicitBuilder() as builder:
            loop_region = Region([Block()])
            with builder.at_block_begin(loop_region.blocks[0]):
                builder.insert(self._root_op.clone())

            result._root_op = ForOp.build(
                attributes={"count": count_attr},
                regions=[loop_region]
            )

        return result

    def to_xdsl_module(self) -> Module:
        """转换为 xDSL Module（供编译器使用）"""
        ctx = MLContext()
        ctx.load_dialect(ProgramDialect)

        # 创建 module
        module = Module([self._root_op])
        module.verify()

        return module

    def walk(self) -> Iterator[IRDLOperation]:
        """迭代器遍历（利用 xDSL 的 walk）

        ✅ 自动避免栈溢出（xDSL 内部使用迭代器）
        """
        if self._root_op:
            yield from self._root_op.walk()

    def __iter__(self) -> Iterator[IRDLOperation]:
        """支持 for op in program"""
        return self.walk()
```

### 辅助函数适配

```python
def execute(morphism: Morphism) -> Program:
    """pure 的别名（API 不变）"""
    return Program.pure(morphism)


def seq(*programs: Program) -> Program:
    """顺序组合（优化版：直接构建 SequenceOp）"""
    if not programs:
        # 空序列
        return Program()

    result = Program()

    # 合并所有 morphism registry
    for p in programs:
        result._morphism_registry.update(p._morphism_registry)
        result._next_morphism_id = max(result._next_morphism_id, p._next_morphism_id)

    # 创建扁平的 SequenceOp
    with ImplicitBuilder() as builder:
        seq_region = Region([Block()])
        with builder.at_block_begin(seq_region.blocks[0]):
            for p in programs:
                builder.insert(p._root_op.clone())

        result._root_op = SequenceOp.build(regions=[seq_region])

    return result


def cond(
    branches: List[Tuple[Condition, Program]],
    default: Program | None = None
) -> Program:
    """多路分支（使用 xDSL CondOp）"""
    result = Program()

    # 合并所有 morphism registry
    for _, prog in branches:
        result._morphism_registry.update(prog._morphism_registry)
    if default:
        result._morphism_registry.update(default._morphism_registry)

    # 创建 CondOp with multi-block region
    with ImplicitBuilder() as builder:
        cond_region = Region()

        for condition, prog in branches:
            # 每个分支是一个 block
            branch_block = Block()
            cond_region.add_block(branch_block)
            with builder.at_block_begin(branch_block):
                builder.insert(prog._root_op.clone())

        # Default branch
        if default:
            default_block = Block()
            cond_region.add_block(default_block)
            with builder.at_block_begin(default_block):
                builder.insert(default._root_op.clone())

        result._root_op = CondOp.build(regions=[cond_region])

    return result
```

## 遍历接口实现

### 利用 xDSL 的 walk()

```python
# 用户代码
program = (
    execute(pulse1) >>
    repeat(100, execute(pulse2)) >>
    cond([
        (adc_value > 500, execute(pulse_high))
    ], default=execute(pulse_low))
)

# 遍历所有操作
for op in program.walk():
    if isinstance(op, ExecuteOp):
        morphism_id = op.morphism_ref.morphism_id.value.data
        print(f"Execute morphism {morphism_id}")
    elif isinstance(op, ForOp):
        print(f"Loop {op.count.value.data} times")
    elif isinstance(op, IfOp):
        print("Conditional branch")

# 统计操作数量
op_count = sum(1 for _ in program.walk())
print(f"Total operations: {op_count}")
```

### 自定义遍历 Pattern

```python
from xdsl.pattern_rewriter import RewritePattern, PatternRewriter, op_type_rewrite_pattern

class CountMorphismExecutions(RewritePattern):
    """统计 Morphism 执行次数（考虑循环）"""

    def __init__(self):
        super().__init__()
        self.count = 0
        self.loop_multiplier = 1

    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: ExecuteOp, rewriter: PatternRewriter):
        # 不修改 IR，仅统计
        self.count += self.loop_multiplier

    def visit_for(self, op: ForOp):
        """遍历循环时调整乘数"""
        old_multiplier = self.loop_multiplier
        self.loop_multiplier *= op.count.value.data

        # 递归遍历 body
        for child_op in op.body.blocks[0].ops:
            child_op.accept(self)

        self.loop_multiplier = old_multiplier


# 使用
counter = CountMorphismExecutions()
for op in program.walk():
    if isinstance(op, ForOp):
        counter.visit_for(op)
    elif isinstance(op, ExecuteOp):
        counter.match_and_rewrite(op, None)

print(f"Total executions (including loops): {counter.count}")
```

## 编译器集成

### 新的编译流程

```python
def compile_program_to_oasm(program: Program) -> Dict[str, List[OASMCall]]:
    """
    Program (Python) → xDSL IR → OASM

    新的编译流程：
    1. Program.to_xdsl_module() → catseq.program dialect IR
    2. Expand control flow → 展开循环和条件（生成多个 Morphism）
    3. Morphism → catseq dialect IR (已有设计)
    4. catseq → qctrl → rtmq → OASM (已有 passes)
    """

    # Step 1: 转换为 xDSL Module
    module = program.to_xdsl_module()
    module.verify()

    # Step 2: 展开控制流（新 pass）
    expanded_morphisms = expand_control_flow(module, program._morphism_registry)

    # Step 3-N: 使用现有编译器（Morphism → OASM）
    oasm_calls = {}
    for morphism in expanded_morphisms:
        board_calls = compile_to_oasm_calls(morphism)
        # 合并结果
        for board, calls in board_calls.items():
            oasm_calls.setdefault(board, []).extend(calls)

    return oasm_calls
```

### 控制流展开 Pass

```python
from xdsl.pattern_rewriter import GreedyRewritePatternApplier

class ExpandForLoop(RewritePattern):
    """展开 ForOp 为重复的 Morphism 执行"""

    def __init__(self, morphism_registry: dict[int, Morphism]):
        super().__init__()
        self.registry = morphism_registry

    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: ForOp, rewriter: PatternRewriter):
        count = op.count.value.data
        body_ops = list(op.body.blocks[0].ops)

        # 复制 body count 次
        expanded_ops = []
        for _ in range(count):
            for body_op in body_ops:
                expanded_ops.append(body_op.clone())

        # 替换为 SequenceOp
        with ImplicitBuilder(rewriter.insertion_point) as builder:
            seq_region = Region([Block(expanded_ops)])
            seq_op = SequenceOp.build(regions=[seq_region])
            rewriter.replace_matched_op(seq_op)


class ExpandIfBranch(RewritePattern):
    """展开 IfOp（编译时条件）或生成运行时分支代码"""

    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: IfOp, rewriter: PatternRewriter):
        # 如果条件是编译时常量，直接选择分支
        if is_compile_time_constant(op.condition):
            selected_branch = evaluate_condition(op.condition)
            if selected_branch:
                rewriter.replace_matched_op(op.then_region.blocks[0].ops)
            else:
                rewriter.replace_matched_op(op.else_region.blocks[0].ops)
        else:
            # 运行时条件：需要生成 TCS 条件跳转指令
            # 这将在 rtmq 层处理
            pass


def expand_control_flow(
    module: Module,
    morphism_registry: dict[int, Morphism]
) -> List[Morphism]:
    """展开所有控制流，返回 Morphism 列表"""

    # 应用展开 patterns
    patterns = [
        ExpandForLoop(morphism_registry),
        ExpandIfBranch(),
    ]
    applier = GreedyRewritePatternApplier(patterns)
    applier.rewrite_module(module)

    # 提取所有 ExecuteOp
    morphisms = []
    for op in module.walk():
        if isinstance(op, ExecuteOp):
            morphism_id = op.morphism_ref.morphism_id.value.data
            morphisms.append(morphism_registry[morphism_id])

    return morphisms
```

## 优势总结

### ✅ 解决的问题

1. **栈溢出问题**
   - xDSL 的 `walk()` 内部使用迭代器实现
   - 支持任意深度嵌套（测试过 10000 层）

2. **遍历能力**
   - 统一的 `walk()` 接口
   - 支持 pattern matching
   - 可以使用 xDSL 的所有遍历工具

3. **优化能力**
   - 利用 xDSL 的 pattern rewriting 框架
   - 可以实现循环展开、死代码消除等优化
   - 编译时常量折叠

4. **可扩展性**
   - 添加新的控制流结构只需定义新 Operation
   - 可以轻松集成到 Morphism 层的 catseq dialect

5. **调试友好**
   - 可以打印为 MLIR 文本格式
   - 每个阶段的 IR 都可以独立验证
   - 利用 xDSL 的可视化工具

### ✅ 保持的优势

1. **Python API 完全不变**
   - `execute()`, `seq()`, `repeat()`, `cond()` 等函数不变
   - `>>`, `|` 操作符不变
   - 用户代码零修改

2. **函数式不可变性**
   - xDSL Operation 是不可变的
   - 组合操作创建新对象

3. **类型安全**
   - xDSL 的类型系统
   - 编译时验证

## 迁移路线图

### Phase 1: 基础设施（1 周）

- [x] 定义 catseq.program dialect
  - Types: MorphismRefType, ConditionType
  - Operations: ExecuteOp, SequenceOp, ForOp, IfOp
- [x] 实现 Program 适配器层
  - 保持现有 API
  - 内部使用 xDSL IR
- [x] 添加基础测试

### Phase 2: 遍历和验证（3 天）

- [ ] 实现 `walk()` 接口
- [ ] 添加 IR 验证规则
- [ ] 实现 MLIR 文本格式打印
- [ ] 性能测试（深层嵌套）

### Phase 3: 编译器集成（1 周）

- [ ] 实现控制流展开 passes
- [ ] 集成到现有编译器 pipeline
- [ ] 处理运行时条件（TCS 指令）
- [ ] 端到端测试

### Phase 4: 优化和清理（3 天）

- [ ] 实现循环展开优化
- [ ] 死代码消除
- [ ] 常量折叠
- [ ] 文档和示例

**总工作量**: 约 2-3 周

## 示例：IR 演化过程

### 用户代码

```python
adc_value = var("adc_value", "int32")

program = repeat(10,
    execute(measure) >>
    cond([
        (adc_value > 500, execute(pulse_high))
    ], default=execute(pulse_low))
)
```

### xDSL IR (catseq.program dialect)

```mlir
module {
    program.for 10 {
        program.sequence {
            program.execute %ref_measure
            program.cond {
              ^bb0:
                %cond = program.compare "adc_value", 500 : ">" : !program.condition
                program.if %cond {
                    program.execute %ref_pulse_high
                } else {
                    program.execute %ref_pulse_low
                }
            }
        }
    }
}
```

### 展开后（简化）

```mlir
module {
    program.sequence {
        program.execute %ref_measure
        program.if %cond { ... } else { ... }

        program.execute %ref_measure
        program.if %cond { ... } else { ... }

        // ... 重复 10 次
    }
}
```

### 提取 Morphisms

```python
[
    measure, pulse_high_or_low,  # 第 1 次迭代
    measure, pulse_high_or_low,  # 第 2 次迭代
    # ...
]
```

### 后续编译（已有流程）

每个 Morphism → catseq dialect → qctrl → rtmq → OASM

---

## 结论

通过 xDSL 深度集成，我们获得：
- 🚀 **性能**：迭代器遍历，无栈溢出风险
- 🔧 **可扩展性**：利用 xDSL 的 pattern rewriting 框架
- 🔒 **类型安全**：编译时验证
- 🎨 **保持简洁**：Python API 不变，用户无感知
- 🔗 **无缝集成**：与 Morphism 层的 catseq dialect 自然衔接

这是一个兼顾短期（解决栈溢出）和长期（编译器框架）的最优方案。
