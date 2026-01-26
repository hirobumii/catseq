"""CatSeq V2 Functional DSL

使用 Functional Naming (Haskell/Category Theory 风格):
- lift(): 将 Morphism 提升到 Program
- delay(): 时间延迟
- set_(): 变量赋值
- match_(): 模式匹配
- if_(): 条件分支
- repeat(): 固定次数循环
- loop(): 变量次数循环

使用示例：
    >>> from catseq.v2.dsl import var, lift, delay, set_, match_, if_, repeat
    >>> from catseq.v2.context import reset_arena
    >>>
    >>> reset_arena()
    >>>
    >>> # 创建变量
    >>> t = var("t")
    >>> count = var("count")
    >>>
    >>> # 构建 Program
    >>> main = (
    ...     set_(t, 100)
    ...     >> delay(t)
    ...     >> match_(t > 50, {
    ...         True: delay(200),
    ...         False: delay(50)
    ...     })
    ... )
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Union

from catseq.v2.context import get_arena
from catseq.v2.program import Program
from catseq.v2.values import Condition, Value, Variable, _ensure_value_id, Numeric

# Re-export from values for convenience
from catseq.v2.values import literal, var  # noqa: F401


# =============================================================================
# Primitive Builders
# =============================================================================

def lift(morphism: Any, **params: Union[Value, Numeric]) -> Program:
    """Lift: 将 Morphism 提升到 Program

    物理语义：执行一个预定义的硬件操作序列。
    代数语义：return :: a -> M a

    Args:
        morphism: Morphism 对象或引用
        **params: 参数绑定（变量名 -> Value 或字面量）

    Returns:
        Program: 新创建的 Program Handle

    Example:
        >>> pulse = lift(ttl_pulse, duration=t, amplitude=0.5)
    """
    arena = get_arena()
    # 将参数转换为 ValueId
    param_ids = {k: _ensure_value_id(v) for k, v in params.items()}
    # 使用 Python object id 作为 morphism_ref
    node_id = arena.lift(id(morphism), param_ids)
    return Program(node_id)


def delay(duration: Union[Value, Numeric], max_hint: Optional[int] = None) -> Program:
    """Delay: 时间延迟

    物理语义：等待指定时间。
    支持变量时长（运行时确定）。

    Args:
        duration: 延迟时长（Value 或字面量）
        max_hint: 最大时长提示（用于编译优化）

    Returns:
        Program: 新创建的 Program Handle

    Example:
        >>> p1 = delay(100)      # 常量延迟
        >>> p2 = delay(t)        # 变量延迟
        >>> p3 = delay(t + 50)   # 表达式延迟
    """
    arena = get_arena()
    duration_id = _ensure_value_id(duration)
    node_id = arena.delay(duration_id, max_hint)
    return Program(node_id)


def set_(target: Variable, value: Union[Value, Numeric]) -> Program:
    """Set: 变量赋值

    物理语义：更新寄存器/变量值。

    Args:
        target: 目标变量（必须是 Variable）
        value: 赋值表达式

    Returns:
        Program: 新创建的 Program Handle

    Example:
        >>> t = var("t")
        >>> p = set_(t, 100)
        >>> p2 = set_(t, t + 10)
    """
    arena = get_arena()
    value_id = _ensure_value_id(value)
    node_id = arena.set_var(target.id, value_id)
    return Program(node_id)


def identity() -> Program:
    """Identity: 空操作

    物理语义：什么都不做（零时长）。
    代数语义：id :: a -> a

    Returns:
        Program: 新创建的 Program Handle
    """
    arena = get_arena()
    node_id = arena.identity()
    return Program(node_id)


# =============================================================================
# Combinators
# =============================================================================

def then(*programs: Program) -> Program:
    """Then: 顺序组合多个 Program

    等价于 p1 >> p2 >> p3 >> ...

    Args:
        *programs: 要组合的 Program 列表

    Returns:
        Program: 组合后的 Program Handle

    Example:
        >>> seq = then(p1, p2, p3)  # 等价于 p1 >> p2 >> p3
    """
    if not programs:
        return identity()
    result = programs[0]
    for p in programs[1:]:
        result = result >> p
    return result


def loop(count: Union[Value, int], body: Program) -> Program:
    """Loop: 循环

    物理语义：硬件循环（FPGA loop 原语）。
    支持变量次数。

    Args:
        count: 循环次数（Value 或字面量）
        body: 循环体

    Returns:
        Program: 新创建的 Program Handle

    Example:
        >>> n = var("n")
        >>> looped = loop(n, pulse)  # 循环 n 次
    """
    arena = get_arena()
    count_id = _ensure_value_id(count)
    node_id = arena.loop_(count_id, body.id)
    return Program(node_id)


def repeat(n: int, body: Program) -> Program:
    """Repeat: 固定次数循环

    物理语义：硬件循环，编译时已知次数。

    Args:
        n: 循环次数（整数常量）
        body: 循环体

    Returns:
        Program: 新创建的 Program Handle

    Example:
        >>> repeated = repeat(10, pulse)  # 循环 10 次
    """
    arena = get_arena()
    count_id = arena.literal(n)
    node_id = arena.loop_(count_id, body.id)
    return Program(node_id)


# =============================================================================
# Branching
# =============================================================================

def match_(
    subject: Union[Value, Condition],
    cases: dict[Any, Program],
    default: Optional[Program] = None,
) -> Program:
    """Match: 模式匹配

    物理语义：硬件分支（FPGA switch）。
    代数语义：case 表达式。

    Args:
        subject: 匹配主体（Value 或 Condition）
        cases: 分支字典（key -> Program）
        default: 默认分支（可选）

    Returns:
        Program: 新创建的 Program Handle

    Example:
        >>> result = match_(x > 50, {
        ...     True: do_high(),
        ...     False: do_low()
        ... })
    """
    arena = get_arena()

    # 获取 subject id
    if isinstance(subject, (Value, Condition)):
        subject_id = subject.id
    else:
        subject_id = arena.literal(int(subject))

    # 转换 cases：将 key 转换为 int
    case_ids: dict[int, int] = {}
    for key, prog in cases.items():
        # 将 key 转换为 int (True -> 1, False -> 0)
        if isinstance(key, bool):
            int_key = 1 if key else 0
        else:
            int_key = int(key)
        case_ids[int_key] = prog.id

    default_id = default.id if default else None
    node_id = arena.match_(subject_id, case_ids, default_id)
    return Program(node_id)


def if_(
    condition: Condition,
    then_: Program,
    else_: Optional[Program] = None,
) -> Program:
    """If: 条件分支

    match_ 的语法糖。

    Args:
        condition: 条件表达式
        then_: 条件为真时执行
        else_: 条件为假时执行（可选）

    Returns:
        Program: 新创建的 Program Handle

    Example:
        >>> result = if_(x > 0, do_positive(), do_negative())
    """
    cases: dict[Any, Program] = {True: then_}
    if else_:
        cases[False] = else_
    return match_(condition, cases, default=else_)


# =============================================================================
# Function Definition
# =============================================================================

def apply(func: Program, *args: Union[Value, Numeric]) -> Program:
    """Apply: 函数调用

    物理语义：子程序调用。

    Args:
        func: 函数定义（Program，通常是 FuncDef 节点）
        *args: 实参列表

    Returns:
        Program: 新创建的 Program Handle

    Example:
        >>> result = apply(my_func, x, 100)
    """
    arena = get_arena()
    arg_ids = [_ensure_value_id(a) for a in args]
    node_id = arena.apply(func.id, arg_ids)
    return Program(node_id)


def func_def(
    name: str,
    params: list[Variable],
    body: Program,
) -> Program:
    """FuncDef: 函数定义

    物理语义：可复用的子程序。

    Args:
        name: 函数名
        params: 形参列表（Variable）
        body: 函数体

    Returns:
        Program: 新创建的 Program Handle（指向 FuncDef 节点）

    Example:
        >>> t = var("_arg_pulse_t")
        >>> pulse_func = func_def("pulse", [t], delay(t))
    """
    arena = get_arena()
    param_ids = [p.id for p in params]
    node_id = arena.func_def(name, param_ids, body.id)
    return Program(node_id)


def subroutine(func: Callable[..., Program]) -> Callable[..., Program]:
    """装饰器: 将 Python 函数提升为硬件子程序

    自动为参数创建 Variable，并记录函数定义。

    Args:
        func: 接受 Variable 参数并返回 Program 的函数

    Returns:
        调用生成器函数

    Example:
        >>> @subroutine
        ... def pulse_and_wait(t: Variable) -> Program:
        ...     return lift(pulse, duration=t) >> delay(t * 2)
        >>>
        >>> result = pulse_and_wait(100)  # 调用子程序
    """
    import inspect
    
    sig = inspect.signature(func)
    arena = get_arena()

    # 为每个参数创建 Variable
    args: list[Variable] = []
    for param_name in sig.parameters:
        arg = var(f"_arg_{func.__name__}_{param_name}")
        args.append(arg)

    # 执行函数获取 body
    body = func(*args)

    # 创建函数定义
    func_node = func_def(func.__name__, args, body)

    # 返回调用生成器
    def caller(*call_args: Union[Value, Numeric]) -> Program:
        return apply(func_node, *call_args)

    caller.__name__ = func.__name__
    caller.__doc__ = func.__doc__
    return caller


# =============================================================================
# Measurement
# =============================================================================

def measure(target: Variable, source: int) -> Program:
    """Measure: 测量

    物理语义：从硬件读取测量结果。

    Args:
        target: 存储结果的变量
        source: 测量源（channel id 或其他标识）

    Returns:
        Program: 新创建的 Program Handle

    Example:
        >>> result = var("result")
        >>> m = measure(result, channel_id=0)
    """
    arena = get_arena()
    node_id = arena.measure(target.id, source)
    return Program(node_id)
