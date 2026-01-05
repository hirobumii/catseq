"""
Purely functional Program API (Haskell/Idris style).

This module provides a monadic interface for building quantum control programs
with control flow (loops, conditionals) and runtime variables.
"""

from dataclasses import dataclass
from typing import Callable, List, Tuple
from .morphism import Morphism
from .ast.program_ast import (
    ProgramNode,
    MorphismStmt,
    SequenceStmt,
    ForLoopStmt,
    IfStmt,
)
from .ast.variables import (
    RuntimeVar,
    CompileTimeParam,
    get_allocator,
)
from .ast.expressions import Condition


@dataclass(frozen=True)
class Program:
    """Program Monad（类似 Haskell 的 IO Monad）

    表示一个可能包含控制流的量子控制程序。
    """
    _ast: ProgramNode

    def __rshift__(self, other: 'Program') -> 'Program':
        """>> 操作符：顺序组合（丢弃左边的结果）

        类似 Haskell: p1 >> p2

        例如：
            program = execute(pulse1) >> execute(pulse2) >> execute(pulse3)
        """
        if not isinstance(other, Program):
            return NotImplemented

        # 优化：扁平化连续的 SequenceStmt
        if isinstance(self._ast, SequenceStmt) and isinstance(other._ast, SequenceStmt):
            # 两者都是序列，合并
            combined_stmts = self._ast.statements + other._ast.statements
            return Program(SequenceStmt(combined_stmts))
        elif isinstance(self._ast, SequenceStmt):
            # 左边是序列，追加右边
            combined_stmts = self._ast.statements + (other._ast,)
            return Program(SequenceStmt(combined_stmts))
        elif isinstance(other._ast, SequenceStmt):
            # 右边是序列，前置左边
            combined_stmts = (self._ast,) + other._ast.statements
            return Program(SequenceStmt(combined_stmts))
        else:
            # 都不是序列，创建新序列
            return Program(SequenceStmt((self._ast, other._ast)))

    @staticmethod
    def pure(morphism: Morphism) -> 'Program':
        """将 Morphism 提升到 Program Monad

        类似 Haskell: return :: a -> m a

        例如：
            prog = Program.pure(pulse)
        """
        return Program(MorphismStmt(morphism))

    def replicate(self, n: int | CompileTimeParam) -> 'Program':
        """重复 n 次

        类似 Haskell: replicateM n p

        例如：
            program = execute(pulse).replicate(100)
        """
        if isinstance(n, int):
            if n <= 0:
                raise ValueError("Replication count must be positive")
        elif isinstance(n, CompileTimeParam):
            # 编译时参数，暂不验证
            pass
        else:
            raise TypeError(f"Count must be int or CompileTimeParam, got {type(n)}")

        return Program(ForLoopStmt(
            loop_var="_",
            count=n,
            body=self._ast
        ))

    def when(self, condition: Condition) -> 'Program':
        """条件执行（when True）

        类似 Haskell: when condition action

        例如：
            program = execute(pulse_high).when(adc_value > threshold)
        """
        return Program(IfStmt(
            condition=condition,
            then_branch=self._ast,
            else_branch=None
        ))

    def unless(self, condition: Condition) -> 'Program':
        """条件执行（when False）

        类似 Haskell: unless condition action

        例如：
            program = execute(pulse_low).unless(adc_value > threshold)
        """
        return Program(IfStmt(
            condition=condition.negate(),
            then_branch=self._ast,
            else_branch=None
        ))

    def to_ast(self) -> ProgramNode:
        """返回内部 AST"""
        return self._ast

    def __str__(self) -> str:
        """可读的字符串表示"""
        return f"Program({self._pretty_print(self._ast)})"

    def _pretty_print(self, node: ProgramNode, indent: int = 0) -> str:
        """递归打印 AST 结构"""
        prefix = "  " * indent

        if isinstance(node, MorphismStmt):
            return f"Execute({node.morphism})"
        elif isinstance(node, SequenceStmt):
            items = [self._pretty_print(stmt, indent + 1) for stmt in node.statements]
            return f"Seq[\n{prefix}  " + f",\n{prefix}  ".join(items) + f"\n{prefix}]"
        elif isinstance(node, ForLoopStmt):
            body_str = self._pretty_print(node.body, indent + 1)
            return f"For({node.count} times)[\n{prefix}  {body_str}\n{prefix}]"
        elif isinstance(node, IfStmt):
            then_str = self._pretty_print(node.then_branch, indent + 1)
            if node.else_branch:
                else_str = self._pretty_print(node.else_branch, indent + 1)
                return f"If(...)[\n{prefix}  Then: {then_str}\n{prefix}  Else: {else_str}\n{prefix}]"
            else:
                return f"If(...)[\n{prefix}  {then_str}\n{prefix}]"
        else:
            return f"<Unknown: {type(node).__name__}>"


# ========== 辅助函数（函数式风格）==========

def execute(morphism: Morphism) -> Program:
    """pure 的别名，更直观

    例如：
        program = execute(pulse)
    """
    return Program.pure(morphism)


def seq(*programs: Program) -> Program:
    """顺序组合多个 Program

    类似 Haskell: sequence [p1, p2, p3]

    例如：
        program = seq(
            execute(pulse1),
            execute(pulse2),
            execute(pulse3)
        )
    """
    if not programs:
        return Program(SequenceStmt(()))

    result = programs[0]
    for p in programs[1:]:
        result = result >> p
    return result


def repeat(n: int | CompileTimeParam, program: Program) -> Program:
    """重复 n 次（replicate 的别名）

    例如：
        program = repeat(100, execute(pulse))
    """
    return program.replicate(n)


def cond(
    branches: List[Tuple[Condition, Program]],
    default: Program | None = None
) -> Program:
    """多路分支（类似 Haskell 的 guards）

    例如：
        program = cond([
            (adc_value > 1000, execute(pulse_very_high)),
            (adc_value > 500,  execute(pulse_high)),
            (adc_value > 100,  execute(pulse_mid)),
        ], default=execute(pulse_low))

    类似 Haskell:
        | adc_value > 1000 = pulse_very_high
        | adc_value > 500  = pulse_high
        | adc_value > 100  = pulse_mid
        | otherwise        = pulse_low
    """
    if not branches:
        if default:
            return default
        else:
            return Program(SequenceStmt(()))  # 空程序

    # 递归构建嵌套的 if-else
    condition, then_prog = branches[0]

    if len(branches) > 1 or default:
        else_prog = cond(branches[1:], default)
        return Program(IfStmt(
            condition=condition,
            then_branch=then_prog._ast,
            else_branch=else_prog._ast
        ))
    else:
        # 只有一个分支，没有 else
        return Program(IfStmt(
            condition=condition,
            then_branch=then_prog._ast,
            else_branch=None
        ))


def if_then_else(
    condition: Condition,
    then_prog: Program,
    else_prog: Program
) -> Program:
    """二路分支（cond 的简化版）

    例如：
        program = if_then_else(
            adc_value > threshold,
            then_prog=execute(pulse_high),
            else_prog=execute(pulse_low)
        )
    """
    return cond([(condition, then_prog)], default=else_prog)


def var(name: str, var_type: str = "int32") -> RuntimeVar:
    """声明运行时变量（类似 Haskell 的 newIORef）

    例如：
        adc_value = var("adc_value", "int32")
        threshold = var("threshold", "int32")
        flag = var("ready", "bool")
    """
    allocator = get_allocator()
    register_id = allocator.allocate(name)
    return RuntimeVar(name, register_id, var_type)


# ========== 比较操作符辅助函数 ==========

def _create_comparison(var: RuntimeVar, op: str, value: int | float) -> Condition:
    """创建比较条件的辅助函数"""
    return Condition.from_comparison(var, op, value)


# 为 RuntimeVar 添加比较操作符（Monkey patching）
def _add_comparison_operators():
    """为 RuntimeVar 类动态添加比较操作符"""

    def gt(self, other):
        if isinstance(other, (int, float)):
            return _create_comparison(self, ">", other)
        return NotImplemented

    def lt(self, other):
        if isinstance(other, (int, float)):
            return _create_comparison(self, "<", other)
        return NotImplemented

    def ge(self, other):
        if isinstance(other, (int, float)):
            return _create_comparison(self, ">=", other)
        return NotImplemented

    def le(self, other):
        if isinstance(other, (int, float)):
            return _create_comparison(self, "<=", other)
        return NotImplemented

    def eq(self, other):
        if isinstance(other, (int, float)):
            return _create_comparison(self, "==", other)
        return NotImplemented

    def ne(self, other):
        if isinstance(other, (int, float)):
            return _create_comparison(self, "!=", other)
        return NotImplemented

    RuntimeVar.__gt__ = gt
    RuntimeVar.__lt__ = lt
    RuntimeVar.__ge__ = ge
    RuntimeVar.__le__ = le
    RuntimeVar.__eq__ = eq
    RuntimeVar.__ne__ = ne


# 在模块加载时添加比较操作符
_add_comparison_operators()
