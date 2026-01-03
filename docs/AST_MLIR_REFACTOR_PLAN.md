# CatSeq AST 重构计划

## 目标

将 CatSeq 从立即计算的 `Dict[Channel, Lane]` 架构重构为基于 AST 的分层设计，支持：

1. **xdsl/MLIR 编译** - 清晰的 dialect 层次和可验证的 IR
2. **控制流** - 循环（for）和条件分支（if/else）
3. **变量系统** - 编译时参数和运行时变量
4. **函数式组合** - 保持 Monoidal Category 的数学抽象

## 架构设计

### 两层抽象（正确的层次关系）

```
┌─────────────────────────────────────────┐
│  Program 层（最高层，可能时间不确定）     │
│  - 包含 Morphism 执行语句                │
│  - for 循环、if/else 分支                │
│  - 变量定义和赋值                        │
│  - AST: Execute, For, If, Sequence       │
└──────────────┬──────────────────────────┘
               │ 包含
               ↓
┌─────────────────────────────────────────┐
│  Morphism 层（底层，时间确定）           │
│  - Monoidal Category 语义（纯函数式）    │
│  - 组合操作符：@, >>, |                 │
│  - 确定的时长（duration_cycles）         │
│  - AST: Atomic, Sequential, Parallel     │
└──────────────┬──────────────────────────┘
               │
               ↓
         xdsl/MLIR 编译
```

### 关键设计原则

1. **Morphism 是底层抽象**：
   - ✅ 时间完全确定（编译时已知）
   - ✅ 纯函数式（无副作用，可组合）
   - ✅ 数学语义清晰（Monoidal Category）

2. **Program 是高层容器**：
   - ✅ 包含 Morphism 作为执行单元
   - ✅ 添加控制流（循环、分支）
   - ✅ 时长可能不确定（运行时分支）

3. **不能互相转换**：
   - ❌ Program 无法 lift 成 Morphism（时长不确定）
   - ✅ Morphism 可以 lift 成 Program（作为 Execute 语句）

4. **组合性**：
   - Morphism: 使用 `@`, `>>`, `|` 组合
   - Program: 使用 `>>` (Monad) 和 `seq` 组合

### 层次关系示例

```python
# ========== Morphism 层（底层，时间确定）==========

# 原子 Morphism - 时长: 1 + 2500 + 1 = 2502 cycles
pulse = ttl_on(ch1) @ identity(ch1, 10e-6) @ ttl_off(ch1)
print(pulse.total_duration_cycles)  # 2502（编译时已知）

# Morphism 组合 - 时长: 2502 + 2502 = 5004 cycles
sequence = pulse @ pulse
print(sequence.total_duration_cycles)  # 5004（编译时已知）

# 并行 Morphism - 时长: max(2502, 1251) = 2502 cycles
parallel = pulse | (ttl_on(ch2) @ identity(ch2, 5e-6) @ ttl_off(ch2))
print(parallel.total_duration_cycles)  # 2502（编译时已知）

# ========== Program 层（高层，时间可能不确定）==========

# 单个 Morphism 提升到 Program - 时长确定
prog1 = execute(pulse)  # 时长 = 2502 cycles（确定）

# 固定次数循环 - 时长确定（编译时展开）
prog2 = execute(pulse).replicate(100)  # 时长 = 2502 * 100（确定）

# 条件分支 - 时长不确定（运行时决定）
adc_value = var("adc_value", "int32")
prog3 = cond([
    (adc_value > 500, execute(pulse)),      # 分支1: 2502 cycles
    (adc_value > 100, execute(pulse @ pulse))  # 分支2: 5004 cycles
], default=execute(identity(ch1, 1e-6)))    # 分支3: 250 cycles
# prog3 的时长：运行时才知道（取决于 adc_value）

# Program 组合
experiment = (
    execute(pulse)              # 确定: 2502 cycles
    >> prog2                    # 确定: 2502 * 100 cycles
    >> prog3                    # 不确定: 运行时决定
)
# experiment 的总时长：部分确定，部分不确定
```

### 为什么 Program 无法 lift 成 Morphism？

```python
# ❌ 不合法：条件分支的 Program 无法转换为 Morphism
prog = cond([
    (adc_value > 500, execute(pulse_short)),   # 10μs
    (adc_value > 100, execute(pulse_long))     # 50μs
])

# 这个 Program 的时长是多少？编译时不知道！
# 所以无法转换为 Morphism（Morphism 必须有确定时长）

# ✅ 合法：固定循环可以"展开"但仍是 Program
prog = execute(pulse).replicate(100)
# 虽然时长确定 (2502 * 100)，但仍然是 Program
# 因为它包含控制流（循环）

# ✅ 合法：Morphism 可以 lift 成 Program
prog = execute(pulse)
# 简单包装，Program 执行这个 Morphism
```

### 编译时的处理

```python
# 编译器对不同构造的处理：

# 1. Morphism → qctrl IR（逻辑时间 + 指令成本扣除）
pulse = ttl_on(ch1) @ identity(ch1, 10e-6) @ ttl_off(ch1)

# 用户期望：总时长 = 2500 cycles（只有 identity 推进逻辑时间）
print(pulse.total_duration_cycles)  # 2500（不是 2502！）

# 编译为 qctrl IR（逻辑时间戳）:
#   qctrl.ttl_set at 0      (逻辑时间: 0)
#   qctrl.ttl_set at 2500   (逻辑时间: 2500)
# 没有显式 wait，因为编译器会自动计算

# 编译为 RTMQ 汇编（物理时间调整）:
#   cycle 0:    AMK - TTL (ttl_on, 成本=1 cycle)
#   cycle 1:    wait_mu(2498)  ← 自动扣除！ 2500 - 1 - 1 = 2498
#   cycle 2499: AMK - TTL (ttl_off, 成本=1 cycle)
#   cycle 2500: 执行完毕
# 实际总时长 = 2500 cycles ✓（匹配用户期望）

# 2. 固定循环 → 可选展开或循环指令
prog = execute(pulse).replicate(100)
# 选项A（小循环）: 编译时展开
# 选项B（大循环）: 生成 RTMQ 循环指令

# 3. 条件分支 → 生成所有分支 + 跳转
prog = cond([
    (adc_value > 500, execute(pulse_high)),
    (adc_value > 100, execute(pulse_low))
])
# 编译为：
#   qprog.if %adc_value > 500 {
#     qprog.execute %pulse_high
#   } else {
#     qprog.if %adc_value > 100 {
#       qprog.execute %pulse_low
#     }
#   }
# 运行时根据条件选择分支
```

### 时间语义和成本模型（关键设计）

#### 逻辑时间 vs 物理时间

**设计原则**：用户只关心逻辑时间，编译器负责物理时间调整

```python
# 用户代码
pulse = ttl_on(ch1) @ identity(ch1, 10e-6) @ ttl_off(ch1)

# 用户期望的逻辑时间轴:
# t=0μs:  ttl_on  (瞬时，不推进时间)
# t=0μs:  identity 开始
# t=10μs: identity 结束
# t=10μs: ttl_off (瞬时，不推进时间)
# 总时长 = 10μs = 2500 cycles

print(pulse.total_duration_cycles)  # 2500 ✓
```

#### 原子操作的时间成本

**逻辑时间成本**（用户可见）：
- `ttl_init()`, `ttl_on()`, `ttl_off()`: **0 cycles**（瞬时操作）
- `rwg_set_carrier()`: **0 cycles**（瞬时操作）
- `identity(duration)`, `wait(duration)`: **duration cycles**（唯一推进逻辑时间的操作）

**物理时间成本**（编译器内部）：
- `ttl_init()`: 实际执行 ~2 cycles（AMK指令）
- `ttl_on()`: 实际执行 ~1 cycle（AMK指令）
- `rwg_set_carrier()`: 实际执行 ~5 cycles（多条指令）
- `wait(duration)`: 实际执行 = duration - 前后指令成本

#### 编译器的自动调整

**当前编译器已实现**（`_pass4_generate_oasm_calls`）：

```python
# 伪代码
for each event in timeline:
    # 逻辑时间戳：用户期望的时间点
    logical_time = event.timestamp_cycles

    # 物理时间：前一个指令实际结束时间
    physical_time = last_op_end_time

    # 自动扣除：wait 时间 = 逻辑时间 - 物理时间
    wait_cycles = logical_time - physical_time

    if wait_cycles > 0:
        emit(wait_mu(wait_cycles))

    emit(event.oasm_calls)
    last_op_end_time = physical_time + event.cost_cycles
```

**示例**：
```python
# 用户代码
ttl_on(ch1) @ identity(ch1, 10e-6) @ ttl_off(ch1)

# LogicalEvent timeline:
# Event 1: ttl_on   at logical_time=0,    cost=1 cycle
# Event 2: ttl_off  at logical_time=2500, cost=1 cycle

# 编译器处理:
# Event 1:
#   logical_time = 0
#   physical_time = 0
#   wait = 0 - 0 = 0（无需 wait）
#   emit: AMK - TTL (ttl_on)
#   last_op_end_time = 0 + 1 = 1
#
# Event 2:
#   logical_time = 2500
#   physical_time = 1
#   wait = 2500 - 1 = 2499 ← 自动扣除！
#   emit: wait_mu(2499)
#   emit: AMK - TTL (ttl_off)
#   last_op_end_time = 2499 + 1 = 2500
#
# 最终 OASM:
#   AMK - TTL (ttl_on)   # cycle 0
#   wait_mu(2499)        # cycle 1-2499
#   AMK - TTL (ttl_off)  # cycle 2500
# 实际总时长 = 2500 cycles ✓
```

#### MLIR 编译器的实现

**关键要求**：新的 MLIR 编译器必须保持这个时间语义

1. **catseq IR**: 只记录逻辑时间
   ```mlir
   %on = catseq.atomic<"ttl_on"> {duration = 0}
   %id = catseq.identity {duration = 2500}
   %off = catseq.atomic<"ttl_off"> {duration = 0}
   %pulse = catseq.compos %on, %id
   %result = catseq.compos %pulse, %off
   ```

2. **qctrl IR**: 逻辑时间戳
   ```mlir
   qctrl.ttl_set at 0     {cost_estimate = 1}
   qctrl.ttl_set at 2500  {cost_estimate = 1}
   ```

3. **rtmq IR → OASM**: 物理时间调整（与现有编译器相同逻辑）
   - 计算 `wait_cycles = next_logical_time - current_physical_time`
   - 自动扣除指令执行成本

**测试要求**：
```python
# 验收测试
pulse = ttl_on(ch1) @ identity(ch1, 10e-6) @ ttl_off(ch1)
oasm_calls_old = compile_to_oasm_legacy(pulse)
oasm_calls_new = compile_to_oasm_mlir(pulse)

# 必须生成完全相同的 OASM 序列
assert oasm_calls_old == oasm_calls_new
# 必须包含 wait_mu(2499)，不是 wait_mu(2500)
assert any(call.args == (2499,) for call in oasm_calls_new[...])
```

### Morphism AST 设计

**核心数据结构** (`catseq/ast/morphism_ast.py`):

```python
@dataclass(frozen=True)
class MorphismAST:
    """AST 基类"""
    pass

@dataclass(frozen=True)
class AtomicNode(MorphismAST):
    """原子操作节点"""
    atomic_op: AtomicMorphism

@dataclass(frozen=True)
class SequentialNode(MorphismAST):
    """串行组合: left @ right 或 left >> right"""
    left: MorphismAST
    right: MorphismAST
    composition_type: str  # "strict" (@) 或 "auto" (>>)

@dataclass(frozen=True)
class ParallelNode(MorphismAST):
    """并行组合: left | right"""
    left: MorphismAST
    right: MorphismAST
    # 显式 identity 补齐（关键设计）
    left_padding_cycles: int = 0
    right_padding_cycles: int = 0

@dataclass(frozen=True)
class IdentityNode(MorphismAST):
    """Identity morphism（纯等待）"""
    duration_cycles: int
    channels: FrozenSet[Channel] = frozenset()
```

**关键设计决策**：
- ✅ **直接存储 AST**：`Morphism(_ast=...)`
- ✅ **lanes 延迟计算**：通过 `@cached_property` 从 AST 生成
- ✅ **显式 identity 补齐**：`ParallelNode` 记录 padding 元数据

### Morphism 类修改

**修改文件**: `catseq/morphism.py`

```python
@dataclass(frozen=True)
class Morphism:
    """Morphism - 基于 AST 的实现"""
    _ast: MorphismAST  # 主存储

    @cached_property
    def lanes(self) -> Dict[Channel, Lane]:
        """延迟计算：从 AST 生成 lanes（向后兼容）"""
        return self._ast_to_lanes(self._ast)

    def to_ast(self) -> MorphismAST:
        """直接返回内部 AST"""
        return self._ast

    # 操作符构建 AST 节点
    def __matmul__(self, other) -> 'Morphism':
        """@ 操作符"""
        ast = SequentialNode(
            left=self._ast,
            right=other._ast,
            composition_type="strict"
        )
        return Morphism(_ast=ast)

    def __or__(self, other) -> 'Morphism':
        """| 操作符（自动时间对齐）"""
        left_dur = self.total_duration_cycles
        right_dur = other.total_duration_cycles

        ast = ParallelNode(
            left=self._ast,
            right=other._ast,
            left_padding_cycles=max(0, right_dur - left_dur),
            right_padding_cycles=max(0, left_dur - right_dur)
        )
        return Morphism(_ast=ast)
```

### Program AST 设计

**核心数据结构** (`catseq/ast/program_ast.py`):

```python
@dataclass(frozen=True)
class ProgramNode:
    """Program AST 基类"""
    pass

@dataclass(frozen=True)
class MorphismStmt(ProgramNode):
    """执行 Morphism"""
    morphism: MorphismAST

@dataclass(frozen=True)
class SequenceStmt(ProgramNode):
    """顺序执行语句"""
    statements: tuple[ProgramNode, ...]

@dataclass(frozen=True)
class ForLoopStmt(ProgramNode):
    """for 循环"""
    loop_var: str
    count: int | 'CompileTimeParam'
    body: ProgramNode

@dataclass(frozen=True)
class IfStmt(ProgramNode):
    """条件分支（基于 RTMQ PTR 跳转）"""
    condition: 'RuntimeVar'  # TCS 寄存器值
    then_branch: ProgramNode
    else_branch: ProgramNode | None = None
```

### 变量系统

**文件**: `catseq/ast/variables.py`

```python
@dataclass(frozen=True)
class CompileTimeParam:
    """编译时参数（Python 常量）"""
    name: str
    value: Any  # int, float, etc.

@dataclass(frozen=True)
class RuntimeVar:
    """运行时变量（RTMQ TCS 寄存器）"""
    name: str
    register_id: int  # TCS 寄存器编号 ($xx)
    var_type: str  # "int32", "bool"
```

### 纯函数式 Program API（Haskell/Idris 风格）

**文件**: `catseq/program.py`

**设计原则**：
1. **表达式导向**：所有构造都是表达式，都返回 ProgramNode
2. **Monad 组合**：使用 `>>` 和 `>>=` 风格的组合子
3. **模式匹配风格**：条件分支使用 `cond` 组合子

#### 核心 Monad: Program

```python
@dataclass(frozen=True)
class Program:
    """Program Monad（类似 Haskell 的 IO Monad）"""
    _ast: ProgramNode

    # Monad 基本操作
    def __rshift__(self, other: 'Program') -> 'Program':
        """>> 操作符：顺序组合（丢弃左边的结果）

        类似 Haskell: p1 >> p2
        """
        return Program(SequenceStmt((self._ast, other._ast)))

    def bind(self, f: Callable[['RuntimeVar'], 'Program']) -> 'Program':
        """>>= 操作符：monadic bind

        类似 Haskell: p >>= \x -> ...
        """
        # 实现延迟到运行时的值传递
        ...

    @staticmethod
    def pure(morphism: Morphism) -> 'Program':
        """将 Morphism 提升到 Program Monad

        类似 Haskell: return :: a -> m a
        """
        return Program(MorphismStmt(morphism.to_ast()))

    def replicate(self, n: int) -> 'Program':
        """重复 n 次

        类似 Haskell: replicateM n p
        """
        return Program(ForLoopStmt(
            loop_var="_",
            count=n,
            body=self._ast
        ))

    def when(self, condition: 'Condition') -> 'Program':
        """条件执行（when True）

        类似 Haskell: when condition action
        """
        return Program(IfStmt(
            condition=condition,
            then_branch=self._ast,
            else_branch=None
        ))

    def unless(self, condition: 'Condition') -> 'Program':
        """条件执行（when False）

        类似 Haskell: unless condition action
        """
        return Program(IfStmt(
            condition=condition.negate(),
            then_branch=self._ast,
            else_branch=None
        ))

# 辅助函数
def execute(morphism: Morphism) -> Program:
    """pure 的别名，更直观"""
    return Program.pure(morphism)

def seq(*programs: Program) -> Program:
    """顺序组合多个 Program

    类似 Haskell: sequence [p1, p2, p3]
    """
    if not programs:
        return Program(SequenceStmt(()))
    result = programs[0]
    for p in programs[1:]:
        result = result >> p
    return result

def repeat(n: int, program: Program) -> Program:
    """重复 n 次（replicate 的别名）"""
    return program.replicate(n)
```

#### 条件分支：cond 组合子

```python
@dataclass(frozen=True)
class Condition:
    """条件表达式（纯数据）"""
    _expr: Expr  # 内部表达式树

    def __and__(self, other: 'Condition') -> 'Condition':
        return Condition(BinOp("&&", self._expr, other._expr))

    def __or__(self, other: 'Condition') -> 'Condition':
        return Condition(BinOp("||", self._expr, other._expr))

    def negate(self) -> 'Condition':
        return Condition(UnaryOp("!", self._expr))

def var(name: str, var_type: str = "int32") -> RuntimeVar:
    """声明运行时变量（类似 Haskell 的 newIORef）"""
    return RuntimeVar(name, _allocate_register(), var_type)

def cond(branches: List[Tuple[Condition, Program]],
         default: Program = None) -> Program:
    """多路分支（类似 Haskell 的 guards）

    cond([
        (x > 10,  execute(pulse_high)),
        (x > 5,   execute(pulse_mid)),
    ], default=execute(pulse_low))

    类似 Haskell:
    | x > 10  = pulse_high
    | x > 5   = pulse_mid
    | otherwise = pulse_low
    """
    if not branches:
        return default or Program(SequenceStmt(()))

    condition, then_prog = branches[0]
    else_prog = cond(branches[1:], default)

    return Program(IfStmt(
        condition=condition,
        then_branch=then_prog._ast,
        else_branch=else_prog._ast if else_prog else None
    ))

def if_then_else(condition: Condition,
                 then_prog: Program,
                 else_prog: Program) -> Program:
    """二路分支（cond 的简化版）"""
    return cond([(condition, then_prog)], default=else_prog)
```

#### 使用示例

```python
# 1. 基本顺序执行（类似 Haskell do-notation）
pulse = ttl_on(ch1) @ identity(ch1, 10e-6) @ ttl_off(ch1)

program = (
    execute(pulse)
    >> execute(pulse)
    >> execute(pulse)
)

# 2. 重复执行（replicate）
program = execute(pulse).replicate(100)

# 或使用函数式风格
program = repeat(100, execute(pulse))

# 3. 条件分支（类似 Haskell guards）
threshold = var("threshold", "int32")
adc_value = var("adc_value", "int32")

program = cond([
    (adc_value > 1000,  execute(pulse_very_high)),
    (adc_value > 500,   execute(pulse_high)),
    (adc_value > 100,   execute(pulse_mid)),
], default=execute(pulse_low))

# 4. 条件执行（when/unless）
program = (
    execute(measure_adc)
    >> execute(pulse_high).when(adc_value > threshold)
    >> execute(pulse_low).unless(adc_value > threshold)
)

# 5. 复杂组合（类似 Haskell）
initialize = execute(ttl_init(ch1))
measure = execute(adc_read)
cleanup = execute(ttl_off(ch1))

experiment = (
    initialize
    >> repeat(10,
        measure
        >> cond([
            (adc_value > 500, execute(pulse_high)),
            (adc_value > 100, execute(pulse_mid)),
        ], default=execute(pulse_low))
    )
    >> cleanup
)

# 6. 高阶组合：map 风格
def map_over_channels(channels: List[Channel],
                      f: Callable[[Channel], Morphism]) -> Program:
    """对每个通道应用操作（类似 mapM）"""
    return seq(*[execute(f(ch)) for ch in channels])

program = map_over_channels(
    [ch1, ch2, ch3],
    lambda ch: ttl_on(ch) @ identity(ch, 10e-6) @ ttl_off(ch)
)
```

#### 高级组合子

```python
# for_each: 类似 Haskell 的 forM
def for_each(items: List[Any], f: Callable[[Any], Program]) -> Program:
    """对列表中每个元素应用操作"""
    return seq(*[f(item) for item in items])

# while_loop: 条件循环（需要运行时支持）
def while_loop(condition: Condition, body: Program) -> Program:
    """当条件为真时循环（类似 Haskell 的 whileM）"""
    return Program(WhileLoopStmt(condition, body._ast))

# fold: 累积操作
def fold_programs(programs: List[Program]) -> Program:
    """折叠多个 Program（类似 foldM）"""
    if not programs:
        return Program(SequenceStmt(()))
    return seq(*programs)
```

#### 为什么这个设计更函数式？

1. **表达式导向**：
   - ✅ 所有操作返回 `Program` 对象
   - ✅ 可以链式组合：`p1 >> p2 >> p3`

2. **不可变性**：
   - ✅ 所有数据结构 `frozen=True`
   - ✅ 组合创建新对象，不修改原对象

3. **Monad 抽象**：
   - ✅ `pure` / `execute`: 提升到 Monad
   - ✅ `>>`: 顺序组合
   - ✅ `bind`: monadic bind（如需要）

4. **高阶函数**：
   - ✅ `replicate`, `cond`, `for_each`
   - ✅ 接受函数作为参数

5. **模式匹配风格**：
   - ✅ `cond` 类似 Haskell guards
   - ✅ `when`/`unless` 条件组合子

6. **组合子库**：
   - ✅ 提供丰富的组合原语
   - ✅ 用户可以自定义高阶组合子
```

## xdsl Dialect 映射

### 四层 Dialect 架构

```
catseq dialect  - Morphism 抽象（Atomic, Compos, Tensor, Identity）
    ↓ Lowering
qprog dialect   - Program 控制流（Execute, For, If, Yield）
    ↓ Lowering
qctrl dialect   - 量子控制操作（TTL_Set, Wait, RWG_Load, RWG_Play）
    ↓ Lowering
rtmq dialect    - RTMQ 指令（AMK, SFS, Timer, NOP）
    ↓ Code Gen
OASM DSL / 汇编
```

### catseq Dialect

**文件**: `catseq/mlir/dialects/catseq.py`

```python
@irdl_op_definition
class ComposOp(IRDLOperation):
    """串行组合: %result = catseq.compos %lhs, %rhs"""
    name = "catseq.compos"
    lhs = operand_def(MorphismType)
    rhs = operand_def(MorphismType)
    result = result_def(MorphismType)

@irdl_op_definition
class TensorOp(IRDLOperation):
    """并行组合: %result = catseq.tensor %lhs, %rhs"""
    name = "catseq.tensor"
    lhs = operand_def(MorphismType)
    rhs = operand_def(MorphismType)
    result = result_def(MorphismType)
```

### qprog Dialect（新增）

**文件**: `catseq/mlir/dialects/qprog.py`

```python
@irdl_op_definition
class ForOp(IRDLOperation):
    """硬件 for 循环

    qprog.for %count {
      ^bb0(%i: i32):
        qprog.execute %morphism
        qprog.yield
    }
    """
    name = "qprog.for"
    count = operand_def(IntegerType)
    body = region_def()

@irdl_op_definition
class IfOp(IRDLOperation):
    """条件分支（基于 RTMQ PTR 跳转）

    qprog.if %condition {
      ^then:
        ...
        qprog.yield
    } else {
      ^else:
        ...
        qprog.yield
    }
    """
    name = "qprog.if"
    condition = operand_def(IntegerType)  # TCS 寄存器值
    then_region = region_def()
    else_region = region_def()
```

### RTMQ 条件分支实现

**硬件支持**：RTMQ 通过 `PTR` 寄存器和 `AMK` 指令实现条件跳转

```rtmq
% 条件跳转示例
AMK - $03 3.0 &ADC      % 将 ADC 值加载到 $03
AMK P PTR $03 -10       % 如果 $03 == -1，跳转到 #else_label
% then branch
...
CLO P PTR #end_label    % 跳过 else branch
#else_label:
% else branch
...
#end_label:
```

**Lowering 策略** (`qprog.if → rtmq`):

```python
class LowerIfPattern(RewritePattern):
    """qprog.if → RTMQ 条件跳转"""
    def match_and_rewrite(self, op: IfOp, rewriter):
        # 1. 生成条件求值（保存到 TCS 寄存器）
        # 2. 使用 AMK P PTR 实现条件跳转
        # 3. 生成 then/else 两个分支的代码
        # 4. 使用 CLO P PTR 实现无条件跳转（跳过 else）
        ...
```

## 实施路线图

### Phase 1: AST 基础设施（2 周）

**目标**：建立 Morphism AST，保持向后兼容

**新增文件**：
- `catseq/ast/__init__.py`
- `catseq/ast/morphism_ast.py` - AST 节点定义

**修改文件**：
- `catseq/morphism.py` - 添加 `_ast` 字段和 `to_ast()` 方法
- `catseq/atomic.py` - 集成 AST
- `catseq/types/common.py` - 类型定义

**测试**：
- 所有现有测试通过（向后兼容）
- 新增：AST 构建和缓存测试
- 验证：`lanes` 延迟计算正确性

**验收标准**：
```python
# 现有代码继续工作
pulse = ttl_on(ch1) @ identity(ch1, 10e-6) @ ttl_off(ch1)
print(pulse.lanes)  # 自动从 AST 计算

# 新功能：访问 AST
ast = pulse.to_ast()
assert isinstance(ast, SequentialNode)
```

---

### Phase 2: catseq Dialect（2 周）

**目标**：实现 Morphism AST → catseq IR 转换

**依赖**：
- 在 `pyproject.toml` 添加 `xdsl = "^0.55.4"`

**新增文件**：
- `catseq/mlir/__init__.py`
- `catseq/mlir/dialects/catseq.py` - catseq dialect 定义
- `catseq/mlir/lowering/morphism_to_catseq.py` - AST → IR 转换

**测试**：
- AST → catseq IR 转换
- 验证 IR 结构正确（ComposOp, TensorOp, AtomicOp）
- 打印 IR 并人工检查

**验收标准**：
```python
ast = pulse.to_ast()
module = morphism_to_catseq_ir(ast)
print(module)  # 输出可读的 catseq IR
```

---

### Phase 3: qctrl/rtmq Dialects（2 周）

**目标**：完整的 Morphism 编译流程（不含控制流）

**新增文件**：
- `catseq/mlir/dialects/qctrl.py` - 量子控制 dialect
- `catseq/mlir/dialects/rtmq.py` - RTMQ 硬件 dialect
- `catseq/mlir/lowering/catseq_to_qctrl.py` - catseq → qctrl
- `catseq/mlir/lowering/qctrl_to_rtmq.py` - qctrl → rtmq
- `catseq/mlir/codegen/rtmq_emitter.py` - rtmq → OASM

**参考文件**：
- `catseq/compilation/compiler.py` - 现有编译器逻辑

**测试**：
- 端到端：简单 TTL pulse → OASM
- 对比输出：MLIR 编译器 vs 现有编译器
- 确保生成的 OASM 调用一致

**验收标准**：
```python
pulse = ttl_on(ch1) @ identity(ch1, 10e-6) @ ttl_off(ch1)
oasm_calls_new = compile_to_oasm_mlir(pulse)
oasm_calls_old = compile_to_oasm_legacy(pulse)
assert oasm_calls_new == oasm_calls_old  # 输出一致
```

---

### Phase 4: Program AST + For 循环（2 周）

**目标**：支持固定次数循环

**新增文件**：
- `catseq/ast/program_ast.py` - Program AST 节点
- `catseq/program.py` - 函数式 Program API
- `catseq/mlir/dialects/qprog.py` - qprog dialect
- `catseq/mlir/lowering/program_to_qprog.py` - Program AST → qprog

**测试**：
- 简单 for 循环编译
- 嵌套循环
- 对比 `repeat_morphism()` 的输出

**验收标准**：
```python
pulse = ttl_on(ch1) @ identity(ch1, 10e-6) @ ttl_off(ch1)
program = for_loop(100, execute(pulse))
oasm_calls = compile_program_to_oasm(program)
# 验证生成了正确的循环 RTMQ 指令
```

---

### Phase 5: 变量 + 条件分支（2 周）

**目标**：运行时变量和 if/else

**新增文件**：
- `catseq/ast/variables.py` - 变量系统
- `catseq/ast/expressions.py` - 表达式 AST

**修改文件**：
- `catseq/program.py` - 添加变量支持
- `catseq/mlir/dialects/qprog.py` - 添加 IfOp
- `catseq/mlir/lowering/qprog_to_qctrl.py` - If → RTMQ PTR 跳转

**RTMQ 条件分支实现**：
- 使用 TCS 寄存器存储条件值
- 使用 `AMK P PTR` 实现条件跳转
- 参考：RTMQ ISA 文档 `PTR` 寄存器部分

**测试**：
- 编译时参数替换
- 运行时变量分配（TCS 寄存器）
- 条件分支编译
- 验证生成正确的 RTMQ 跳转指令

**验收标准**：
```python
threshold = runtime_var("threshold", "int32")
program = if_then_else(
    threshold > 500,
    then_branch=execute(pulse_high),
    else_branch=execute(pulse_low)
)
oasm_calls = compile_program_to_oasm(program)
# 验证包含 AMK P PTR 条件跳转指令
```

---

## 关键文件清单

### Phase 1（AST 基础）：
- **新增**: `catseq/ast/morphism_ast.py`
- **修改**: `catseq/morphism.py`, `catseq/atomic.py`
- **测试**: `tests/unit/test_morphism.py`

### Phase 2（catseq Dialect）：
- **新增**: `catseq/mlir/dialects/catseq.py`, `catseq/mlir/lowering/morphism_to_catseq.py`
- **修改**: `pyproject.toml`

### Phase 3（完整流程）：
- **新增**: `catseq/mlir/dialects/{qctrl,rtmq}.py`, `catseq/mlir/lowering/{catseq_to_qctrl,qctrl_to_rtmq}.py`, `catseq/mlir/codegen/rtmq_emitter.py`
- **参考**: `catseq/compilation/compiler.py`

### Phase 4（控制流）：
- **新增**: `catseq/ast/program_ast.py`, `catseq/program.py`, `catseq/mlir/dialects/qprog.py`
- **参考**: `catseq/control.py`

### Phase 5（变量）：
- **新增**: `catseq/ast/variables.py`, `catseq/ast/expressions.py`
- **修改**: `catseq/program.py`, `catseq/mlir/dialects/qprog.py`

---

## 向后兼容策略

### 渐进式迁移

```python
# catseq/compat.py
USE_MLIR_COMPILER = os.getenv("CATSEQ_USE_MLIR", "false") == "true"

def compile_to_oasm_calls(morphism: Morphism, assembler_seq):
    """统一编译 API（特性开关）"""
    if USE_MLIR_COMPILER:
        return compile_to_oasm_mlir(morphism, assembler_seq)
    else:
        return compile_to_oasm_legacy(morphism, assembler_seq)
```

### 性能基准

**目标**：
- AST 构建开销：< 5% vs 现有实现
- 编译时间：< 2x 现有编译器（简单程序）
- 运行时性能：相同（生成相同的 OASM）

---

## 设计优势总结

1. ✅ **清晰的抽象层次**：Morphism（纯函数式）+ Program（命令式）
2. ✅ **显式时间对齐**：ParallelNode 记录 padding，易于理解和调试
3. ✅ **函数式 API**：避免 lambda，使用纯函数组合
4. ✅ **MLIR 原生支持**：自然映射到 dialect/region/block
5. ✅ **硬件条件分支**：利用 RTMQ PTR 寄存器实现真实的条件跳转
6. ✅ **向后兼容**：现有代码无需修改，渐进式迁移
7. ✅ **可验证性**：每层 IR 都有类型系统和验证规则
8. ✅ **可扩展性**：易于添加新硬件、新优化、新控制流

---

## 下一步行动

**立即开始 Phase 1**：
1. 创建 `catseq/ast/morphism_ast.py`
2. 修改 `catseq/morphism.py` 添加 AST 支持
3. 运行所有测试，确保向后兼容
4. 添加 AST 相关的新测试

预计完成时间：2 周
