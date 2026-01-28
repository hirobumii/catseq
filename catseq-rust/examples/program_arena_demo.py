#!/usr/bin/env python3
"""ProgramArena 示例 - 使用高层 DSL API

展示如何使用 Pythonic 语法构建带有变量、循环、条件分支的控制流程序。

运行方式:
    cd catseq-rust
    source ~/catseq/.venv/bin/activate
    python examples/program_arena_demo.py
"""

import sys
sys.path.insert(0, "/home/tosaka/catseq")

from catseq.v2.context import reset_arena, arena_node_count, arena_value_count
from catseq.v2.values import var, literal
from catseq.v2.dsl import (
    delay, set_, identity, then,
    loop, repeat, match_, if_,
    lift, func_def, apply, measure,
    subroutine,
)

# ==============================================================================
# Part 1: 变量和表达式 - Python 运算符语法
# ==============================================================================

print("=" * 80)
print("Part 1: 变量和表达式 - Python 运算符语法")
print("=" * 80)

reset_arena()

# 创建变量
x = var("x")
y = var("y")
t = var("t", type_hint="float64")

print(f"\n创建变量:")
print(f"  x = var('x')      -> {x}")
print(f"  y = var('y')      -> {y}")
print(f"  t = var('t', 'float64') -> {t}")

# 算术表达式 - 使用 Python 运算符！
print("\n算术表达式:")
z = x + 10
print(f"  x + 10            -> {z}")

w = y * 2 - 5
print(f"  y * 2 - 5         -> {w}")

expr = (x + 10) * 2
print(f"  (x + 10) * 2      -> {expr}")

neg = -x
print(f"  -x                -> {neg}")

# 比较表达式
print("\n比较表达式:")
cond1 = x > 0
print(f"  x > 0             -> {cond1}")

cond2 = x < 100
print(f"  x < 100           -> {cond2}")

# 逻辑组合
print("\n逻辑组合:")
combined = (x > 0) & (x < 100)
print(f"  (x > 0) & (x < 100) -> {combined}")

negated = ~(x > 0)
print(f"  ~(x > 0)          -> {negated}")

print(f"\nArena 状态: values={arena_value_count()}")

# ==============================================================================
# Part 2: 基础 Program 节点
# ==============================================================================

print("\n" + "=" * 80)
print("Part 2: 基础 Program 节点")
print("=" * 80)

reset_arena()

# Identity - 空操作
id_node = identity()
print(f"\nidentity()          -> {id_node}")

# Delay - 时间延迟
d1 = delay(100)
print(f"delay(100)          -> {d1}")

# 变量延迟
t = var("t")
d2 = delay(t)
print(f"delay(t)            -> {d2}")

# 表达式延迟
d3 = delay(t + 50)
print(f"delay(t + 50)       -> {d3}")

# Set - 变量赋值
counter = var("counter")
s1 = set_(counter, 0)
print(f"set_(counter, 0)    -> {s1}")

s2 = set_(counter, counter + 1)
print(f"set_(counter, counter + 1) -> {s2}")

print(f"\nArena 状态: nodes={arena_node_count()}, values={arena_value_count()}")

# ==============================================================================
# Part 3: 顺序组合 (>>)
# ==============================================================================

print("\n" + "=" * 80)
print("Part 3: 顺序组合 (>>)")
print("=" * 80)

reset_arena()

# 使用 >> 操作符顺序组合
p1 = delay(100)
p2 = delay(200)
p3 = delay(300)

seq = p1 >> p2 >> p3
print(f"\ndelay(100) >> delay(200) >> delay(300)")
print(f"  -> {seq}")

# 使用 then() 批量组合
seq2 = then(delay(10), delay(20), delay(30), delay(40))
print(f"\nthen(delay(10), delay(20), delay(30), delay(40))")
print(f"  -> {seq2}")

# 组合复杂操作
t = var("t")
counter = var("counter")
program = (
    set_(t, 100)
    >> delay(t)
    >> set_(counter, 0)
    >> delay(50)
    >> set_(counter, counter + 1)
)
print(f"\n复杂序列:")
print(f"  set_(t, 100) >> delay(t) >> set_(counter, 0) >> delay(50) >> set_(counter, counter+1)")
print(f"  -> {program}")

print(f"\nArena 状态: nodes={arena_node_count()}, values={arena_value_count()}")

# ==============================================================================
# Part 4: 循环
# ==============================================================================

print("\n" + "=" * 80)
print("Part 4: 循环")
print("=" * 80)

reset_arena()

# repeat - 固定次数循环
body = delay(100)
looped = repeat(10, body)
print(f"\nrepeat(10, delay(100))")
print(f"  -> {looped}")

# 等价的 replicate 语法
looped2 = delay(100).replicate(10)
print(f"\ndelay(100).replicate(10)")
print(f"  -> {looped2}")

# loop - 变量次数循环
n = var("n")
looped3 = loop(n, delay(100))
print(f"\nloop(n, delay(100))")
print(f"  -> {looped3}")

# 复杂循环体
counter = var("counter")
loop_body = delay(100) >> set_(counter, counter + 1)
complex_loop = loop(n, loop_body)
print(f"\nloop(n, delay(100) >> set_(counter, counter + 1))")
print(f"  -> {complex_loop}")

print(f"\nArena 状态: nodes={arena_node_count()}, values={arena_value_count()}")

# ==============================================================================
# Part 5: 条件分支
# ==============================================================================

print("\n" + "=" * 80)
print("Part 5: 条件分支")
print("=" * 80)

reset_arena()

# if_ - 简单条件
x = var("x")
branched = if_(x > 0, delay(100), delay(50))
print(f"\nif_(x > 0, delay(100), delay(50))")
print(f"  -> {branched}")

# match_ - 模式匹配
mode = var("mode")
matched = match_(mode, {
    0: delay(100),   # 短脉冲
    1: delay(500),   # 中脉冲
    2: delay(1000),  # 长脉冲
}, default=identity())
print(f"\nmatch_(mode, {{0: delay(100), 1: delay(500), 2: delay(1000)}}, default=identity())")
print(f"  -> {matched}")

# 基于条件的 match
x = var("x")
cond = x > 50
result = match_(cond, {
    True: delay(200),
    False: delay(50),
})
print(f"\nmatch_(x > 50, {{True: delay(200), False: delay(50)}})")
print(f"  -> {result}")

print(f"\nArena 状态: nodes={arena_node_count()}, values={arena_value_count()}")

# ==============================================================================
# Part 6: 函数定义和调用
# ==============================================================================

print("\n" + "=" * 80)
print("Part 6: 函数定义和调用")
print("=" * 80)

reset_arena()

# 手动定义函数
param_t = var("_arg_pulse_t")
pulse_body = delay(param_t)
pulse_func = func_def("pulse", [param_t], pulse_body)
print(f"\n# 定义函数: fn pulse(t) {{ delay(t) }}")
print(f"pulse_func = func_def('pulse', [t], delay(t))")
print(f"  -> {pulse_func}")

# 调用函数
call1 = apply(pulse_func, 100)
call2 = apply(pulse_func, 200)
print(f"\napply(pulse_func, 100) -> {call1}")
print(f"apply(pulse_func, 200) -> {call2}")

# 串联多次调用
seq = call1 >> call2
print(f"\napply(pulse_func, 100) >> apply(pulse_func, 200)")
print(f"  -> {seq}")

print(f"\nArena 状态: nodes={arena_node_count()}, values={arena_value_count()}")

# ==============================================================================
# Part 7: @subroutine 装饰器
# ==============================================================================

print("\n" + "=" * 80)
print("Part 7: @subroutine 装饰器")
print("=" * 80)

reset_arena()

@subroutine
def pulse_and_wait(duration, gap):
    """执行脉冲后等待"""
    return delay(duration) >> delay(gap)

print(f"\n@subroutine")
print(f"def pulse_and_wait(duration, gap):")
print(f"    return delay(duration) >> delay(gap)")

# 调用
result1 = pulse_and_wait(100, 50)
result2 = pulse_and_wait(200, 100)
print(f"\npulse_and_wait(100, 50) -> {result1}")
print(f"pulse_and_wait(200, 100) -> {result2}")

# 变量参数
t = var("t")
result3 = pulse_and_wait(t, t * 2)
print(f"pulse_and_wait(t, t * 2) -> {result3}")

print(f"\nArena 状态: nodes={arena_node_count()}, values={arena_value_count()}")

# ==============================================================================
# Part 8: 完整示例 - 带测量反馈的自适应脉冲
# ==============================================================================

print("\n" + "=" * 80)
print("Part 8: 完整示例 - 带测量反馈的自适应脉冲")
print("=" * 80)

reset_arena()

print("""
构建程序:
  result = var("result")
  count = var("count")

  program = (
      set_(count, 0)
      >> repeat(10,
          measure(result, source=0)
          >> if_(result > 500,
              delay(1000),  # 长等待
              delay(100))   # 短等待
          >> set_(count, count + 1)
      )
  )
""")

result = var("result")
count = var("count")

program = (
    set_(count, 0)
    >> repeat(10,
        measure(result, source=0)
        >> if_(result > 500,
            delay(1000),  # 高信号 -> 长等待
            delay(100))   # 低信号 -> 短等待
        >> set_(count, count + 1)
    )
)

print(f"program -> {program}")
print(f"\nArena 状态: nodes={arena_node_count()}, values={arena_value_count()}")

# ==============================================================================
# Part 9: 与 Morphism 集成 (lift)
# ==============================================================================

print("\n" + "=" * 80)
print("Part 9: 与 Morphism 集成 (lift)")
print("=" * 80)

reset_arena()

# 导入 TTL Morphism API
from catseq.v2.ttl import ttl_on, ttl_off, wait, TTLOff
from catseq.v2.context import reset_context
from catseq.types.common import Board, Channel, ChannelType
from catseq.time_utils import us

# 创建通道
ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)

print(f"\n通道: {ch.global_id}")

# Step 1: 定义 OpenMorphism（惰性的，未绑定）
print("\n--- Step 1: 定义 OpenMorphism ---")
pulse_open = ttl_on() >> wait(10*us) >> ttl_off()
print(f"pulse_open = ttl_on() >> wait(10*us) >> ttl_off()")
print(f"  类型: {type(pulse_open).__name__}")

# Step 2: 物化为 ClosedMorphism（绑定通道 + 状态验证）
print("\n--- Step 2: 物化为 ClosedMorphism ---")
reset_context()  # 清空 Morphism Arena
pulse_closed = pulse_open(ch, TTLOff())
print(f"pulse_closed = pulse_open(ch, TTLOff())")
print(f"  类型: {type(pulse_closed).__name__}")
print(f"  node_id: {pulse_closed.node_id}")
print(f"  end_state: {pulse_closed.end_state}")

# Step 3: lift 到 Program 层
print("\n--- Step 3: lift 到 Program ---")
t = var("t")
lifted = lift(pulse_closed, duration=t)
print(f"lifted = lift(pulse_closed, duration=t)")
print(f"  -> {lifted}")

# 在循环中使用
print("\n--- 在循环中使用 ---")
n = var("n")
repeated_pulse = loop(n,
    lift(pulse_closed)
    >> delay(50)  # 间隔
)
print(f"repeated_pulse = loop(n, lift(pulse_closed) >> delay(50))")
print(f"  -> {repeated_pulse}")

print(f"\nArena 状态: nodes={arena_node_count()}, values={arena_value_count()}")

# ==============================================================================
# 总结
# ==============================================================================

print("\n" + "=" * 80)
print("API 总结")
print("=" * 80)

print("""
┌─────────────────────────────────────────────────────────────────────────────┐
│ Value API (catseq.v2.values)                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  var("x")              创建变量                                             │
│  var("x", "float64")   创建带类型提示的变量                                 │
│  literal(42)           创建字面量                                           │
│  x + y, x - y, ...     算术运算 (+, -, *, /, %, -x)                        │
│  x & y, x | y, ...     位运算 (&, |, ^, <<, >>, ~)                         │
│  x > y, x == y, ...    比较运算 (>, <, >=, <=, ==, !=)                     │
│  cond1 & cond2         逻辑与                                               │
│  cond1 | cond2         逻辑或                                               │
│  ~cond                 逻辑非                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ Program DSL (catseq.v2.dsl)                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  delay(duration)       时间延迟                                             │
│  set_(var, value)      变量赋值                                             │
│  identity()            空操作                                               │
│  p1 >> p2              顺序组合                                             │
│  then(p1, p2, p3)      批量顺序组合                                         │
│  repeat(n, body)       固定次数循环                                         │
│  loop(count, body)     变量次数循环                                         │
│  body.replicate(n)     repeat 的便捷语法                                    │
│  if_(cond, then, else) 条件分支                                             │
│  match_(subj, cases)   模式匹配                                             │
│  lift(morph, **params) 提升 Morphism                                        │
│  func_def(name, ...)   函数定义                                             │
│  apply(func, *args)    函数调用                                             │
│  @subroutine           函数装饰器                                           │
│  measure(var, source)  测量                                                 │
└─────────────────────────────────────────────────────────────────────────────┘
""")

print("✅ 示例运行完成")
