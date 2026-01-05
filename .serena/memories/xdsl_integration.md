# xDSL/MLIR 集成架构（v0.2.1）

## 概述

CatSeq v0.2.1 引入了基于 xDSL/MLIR 的现代编译器架构，提供两层编程接口和非递归编译器设计。

## 双层编程接口

### 1. Morphism API（底层硬件控制）
- **基于范畴论**：Monoidal Category 语义
- **组合操作符**：
  - `@` - 严格串行组合（要求状态严格匹配）
  - `>>` - 自动状态推导组合（智能推导中间状态）
  - `|` - 并行组合/张量积（不同通道）
- **使用场景**：直接硬件控制，精确时序要求

### 2. Program API（高层函数式编程）🆕
- **Monad 风格**：受 Haskell/Idris 启发
- **核心操作符**：
  - `>>` - 顺序组合（丢弃左边结果）
  - `.replicate(n)` - 重复 n 次
  - `.when(cond)` - 条件执行
  - `.unless(cond)` - 条件执行（取反）

- **函数组合器**：
  ```python
  execute(morphism)              # 提升 Morphism 到 Program Monad
  seq(p1, p2, p3)               # 顺序组合多个 Program
  repeat(n, program)            # 重复执行
  cond([(c1, p1), (c2, p2)], default=p)  # 多路分支
  if_then_else(c, then_p, else_p)        # 二路分支
  ```

- **运行时变量**：
  ```python
  adc_value = var("adc_value", "int32")  # 声明运行时变量
  condition = adc_value > 500             # 创建条件表达式
  program.when(condition)                 # 条件执行
  ```

## 模块结构

### catseq/ast/ - Program AST 层
```
ast/
├── __init__.py           # 模块导出
├── variables.py          # RuntimeVar, CompileTimeParam, 寄存器分配器
├── expressions.py        # 表达式 AST (BinOp, UnaryOp, VarRef, ConstExpr, Condition)
├── program_ast.py        # Program AST 节点 (MorphismStmt, SequenceStmt, ForLoopStmt, IfStmt)
└── ast_to_ir.py         # 🔑 AST → xDSL IR 非递归转换器
```

**关键类**：
- `Condition`: 条件表达式，内部包含 `Expr` 树
- `BinOp`: 二元操作（比较、逻辑运算）
- `UnaryOp`: 一元操作（逻辑非）
- `RuntimeVar`: 运行时变量（映射到 TCS 寄存器）
- `CompileTimeParam`: 编译时参数

### catseq/dialects/ - xDSL Dialect 层 🆕
```
dialects/
├── __init__.py           # Dialect 模块导出
├── program_dialect.py    # 🔑 Program dialect 定义
└── program_utils.py      # 🔑 非递归遍历工具
```

**program_dialect.py 核心内容**：

#### 类型定义
- `MorphismRefType`: Morphism 引用（通过整数 ID）
  ```mlir
  !program.morphism_ref<42>
  ```
- `ConditionType`: 条件表达式类型
  ```mlir
  !program.condition
  ```
- `LoopVarType`: 循环变量类型
  ```mlir
  !program.loop_var
  ```

#### 控制流操作
- `ExecuteOp`: 执行单个 Morphism
  ```mlir
  program.execute <42>
  ```
- `SequenceOp`: 顺序执行多个操作（带 NoTerminator trait）
  ```mlir
  program.sequence {
      program.execute <1>
      program.execute <2>
  }
  ```
- `ForOp`: 固定次数循环（带 NoTerminator trait）
  ```mlir
  program.for 100 {
      program.execute <42>
  }
  ```
- `IfOp`: 条件分支（带 NoTerminator trait）
  ```mlir
  program.if %cond {
      program.execute <1>
  } else {
      program.execute <2>
  }
  ```

#### 条件操作
- `CompareOp`: 比较操作（生成条件）
  ```mlir
  %cond = program.compare "adc_value", 500 : ">" : !program.condition
  ```
- `LogicalAndOp`: 逻辑与
  ```mlir
  %result = program.and %cond1, %cond2 : !program.condition
  ```
- `LogicalOrOp`: 逻辑或
- `LogicalNotOp`: 逻辑非

**program_utils.py 核心内容**：

#### 非递归遍历（关键！）
```python
def walk_iterative(op: Operation) -> Iterator[Operation]:
    """使用显式栈避免 Python 递归限制"""
    stack = [(op, False)]
    while stack:
        current_op, is_processed = stack.pop()
        if not is_processed:
            yield current_op
            # 将子操作入栈...
```

- `walk_iterative()` - 非递归遍历所有操作
- `walk_iterative_with_depth()` - 带深度信息的遍历
- `count_operations()` - 统计操作总数
- `max_nesting_depth()` - 计算最大嵌套深度

**验证**：成功处理 10,000+ 层嵌套，无栈溢出！

### catseq/program.py - Program Monad API 🆕

**核心类**：
```python
@dataclass(frozen=True)
class Program:
    """Program Monad（类似 Haskell 的 IO Monad）"""
    _ast: ProgramNode  # 内部 AST 表示
    
    def __rshift__(self, other: 'Program') -> 'Program':
        """>> 操作符：顺序组合"""
        
    def replicate(self, n: int | CompileTimeParam) -> 'Program':
        """重复 n 次"""
        
    def when(self, condition: Condition) -> 'Program':
        """条件执行（when True）"""
        
    def unless(self, condition: Condition) -> 'Program':
        """条件执行（when False）"""
```

**辅助函数**：
- `execute(morphism)` - Program.pure 的别名
- `seq(*programs)` - 顺序组合多个 Program
- `repeat(n, program)` - 重复执行
- `cond(branches, default)` - 多路分支
- `if_then_else(cond, then, else)` - 二路分支
- `var(name, type)` - 声明运行时变量

## AST 到 xDSL IR 转换 🔑

### ASTToIRConverter 类

**核心功能**：
1. **Morphism 注册表**：
   - 问题：xDSL IR 不能直接嵌入 Python 对象
   - 解决：用整数 ID 引用 Morphism，维护 `morphism_id → Morphism` 映射
   
2. **非递归转换**：
   - `convert_node_recursive()` - 简单情况用递归（快速）
   - `_convert_node_iterative()` - 深层嵌套用迭代（安全）
   - `_has_deep_nesting()` - 自动检测深度（>50 层）

3. **条件转换**：
   - 将 `Condition` 表达式树转换为 xDSL 操作序列
   - 自动管理 SSA 值和操作依赖
   - 条件操作插入到正确的位置

**转换流程**：
```
Program AST
    ↓
[ASTToIRConverter]
    ↓
xDSL IR (program dialect)
    ↓
[5-Stage Compiler]
    ↓
OASM Calls
```

## NoTerminator Trait 的重要性

### 问题
xDSL 默认要求 single-block region 必须以终止符（terminator）结尾，如：
- `func.return` - 函数返回
- `scf.yield` - SCF 控制流返回值
- `cf.br` - 无条件跳转

### 解决方案
为具有**隐式控制流**的操作添加 `NoTerminator()` trait：

```python
from xdsl.irdl import traits_def
from xdsl.traits import NoTerminator

@irdl_op_definition
class SequenceOp(IRDLOperation):
    name = "program.sequence"
    body = region_def("single_block")
    
    traits = traits_def(NoTerminator())  # 🔑 关键！
```

### 适用场景
- `SequenceOp` - 顺序执行完自然结束
- `ForOp` - 循环体自动继续下一次迭代
- `IfOp` - 分支执行完自动返回（不需要返回值时）
- `ModuleOp` - 顶层容器，不参与控制流

### 不适用场景
需要显式终止符的操作：
- `scf.if` - 需要 `scf.yield` 返回值
- `func.func` - 需要 `func.return`
- 显式分支 - 需要 `cf.br` / `cf.cond_br`

## 非递归设计的关键优势

### 问题
Python 递归深度限制 ~1000 层，对于：
- 深层嵌套循环（100+ 层）
- 复杂条件分支
- 大型程序结构

会导致 `RecursionError: maximum recursion depth exceeded`

### 解决方案

#### 1. 遍历层面
```python
# ❌ xDSL 内置 walk() - 递归实现
for op in root_op.walk():
    ...  # 深度 > 1000 时栈溢出

# ✅ walk_iterative() - 显式栈
for op in walk_iterative(root_op):
    ...  # 支持任意深度
```

#### 2. 转换层面
```python
# ❌ 递归转换
def convert_node(node):
    if isinstance(node, ForLoop):
        body_op = convert_node(node.body)  # 递归调用
        return ForOp(body_op)

# ✅ 迭代转换
def _convert_node_iterative(root):
    stack = [(root, 'pre')]
    converted = {}
    while stack:
        node, phase = stack.pop()
        # 使用显式栈处理...
```

### 验证结果
- ✅ 遍历：10,000 层嵌套成功
- ✅ 转换：1,000 层嵌套成功
- ✅ IR 验证：通过 xDSL 验证器
- ✅ 测试：19/19 全部通过

## 编译流程

### 完整流程
```
用户代码 (Program API / Morphism API)
    ↓
Program AST (program_ast.py)
    ↓
xDSL IR (program dialect)  [ast_to_ir.py]
    ↓
[未来] Pattern Rewriting & Optimization
    ↓
5-Stage Compiler (compilation/)
    ↓
OASM Calls
    ↓
RTMQ 汇编
    ↓
硬件执行
```

### 当前状态
- ✅ Program API → AST
- ✅ AST → xDSL IR
- ✅ 非递归遍历和转换
- ⏳ xDSL IR → OASM（进行中）
- ⏳ 优化 Passes（待开发）

## 测试覆盖

### tests/test_program_dialect_basic.py
- ExecuteOp, SequenceOp, ForOp, IfOp 基础测试
- 嵌套循环测试
- 深层嵌套测试（10,000 层）
- 条件操作测试
- IR 打印测试
- **结果**: 9/9 通过 ✅

### tests/unit/test_ast_to_ir.py
- 单个 Morphism 转换
- Sequence 转换
- ForLoop 转换（包括嵌套）
- IfStmt 转换（简单和复杂条件）
- 深层嵌套转换（1,000 层）
- Morphism 注册表测试
- Module 生成测试
- **结果**: 10/10 通过 ✅

### tests/unit/test_program_api.py
- Program Monad 操作符测试
- 函数组合器测试
- 运行时变量测试
- 条件执行测试

### tests/integration/test_program_examples.py
- 端到端示例测试
- 实际使用场景验证

## 导出的 API

### catseq/__init__.py 新增导出

**Program API**:
```python
from .program import (
    Program,        # Program Monad 类
    execute,        # execute(morphism) -> Program
    seq,            # seq(*programs) -> Program
    repeat,         # repeat(n, program) -> Program
    cond,           # cond([(c1, p1), ...], default=p) -> Program
    if_then_else,   # if_then_else(c, then_p, else_p) -> Program
    var,            # var(name, type) -> RuntimeVar
)
```

**变量管理**:
```python
from .ast.variables import (
    CompileTimeParam,  # 编译时参数
    RuntimeVar,        # 运行时变量
    reset_allocator,   # 重置寄存器分配器
)
```

**AST 节点**（高级用户）:
```python
from .ast.program_ast import (
    ProgramNode,      # AST 节点基类
    MorphismStmt,     # 执行 Morphism
    SequenceStmt,     # 顺序执行
    ForLoopStmt,      # 循环
    IfStmt,           # 条件分支
)
```

## 设计原则总结

1. **双层抽象**：底层精确控制 + 高层函数式编程
2. **类型安全**：编译时状态验证，防止硬件错误
3. **非递归设计**：支持任意深度嵌套，无性能瓶颈
4. **标准化 IR**：xDSL/MLIR 兼容，支持模式重写优化
5. **不可变性**：函数式设计，所有操作返回新对象
6. **清晰语义**：通过 traits 明确操作语义

## 下一步开发

1. **编译器后端**：
   - xDSL IR → OASM 代码生成
   - 实现 IR 到 5-Stage Compiler 的桥接
   
2. **优化 Passes**：
   - 循环展开（loop unrolling）
   - 死代码消除（dead code elimination）
   - 常量折叠（constant folding）
   
3. **运行时条件**：
   - TCS 指令映射
   - 硬件条件分支实现
   
4. **可视化**：
   - xDSL IR 可视化工具
   - 编译流程调试器
