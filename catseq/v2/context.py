"""CatSeq V2 隐式上下文管理

提供全局 CompilerContext（Morphism Arena）和 ProgramArena（Program DSL）。

使用示例：
    >>> from catseq.v2.context import clear_context, reset_context, get_arena
    >>> from catseq.v2.ttl import ttl_on, ttl_off, wait, TTLOff
    >>> from catseq.types.common import Board, Channel, ChannelType
    >>> from catseq.time_utils import us
    >>>
    >>> ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)
    >>>
    >>> # 无需显式创建 ctx
    >>> pulse = ttl_on() >> wait(10*us) >> ttl_off()
    >>> result = pulse(ch, TTLOff())  # 自动使用全局 ctx
    >>>
    >>> # 清空所有节点（复用同一 ctx）
    >>> clear_context()
    >>>
    >>> # 或完全重置（释放内存）
    >>> reset_context()

ProgramArena 示例：
    >>> from catseq.v2.context import get_arena, reset_arena
    >>>
    >>> arena = get_arena()
    >>> x = arena.variable("x", "int32")
    >>> delay_node = arena.delay(x, None)
    >>>
    >>> # 清空 Arena
    >>> reset_arena()
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

from catseq.v2.opcodes import OpCode
from catseq.time_utils import CLOCK_FREQ_HZ

if TYPE_CHECKING:
    import catseq_rs

# =============================================================================
# CompilerContext (Morphism Arena) - 用于 Morphism 数据流
# =============================================================================

# 全局上下文（惰性初始化）
_global_context: "catseq_rs.CompilerContext | None" = None


def get_context() -> "catseq_rs.CompilerContext":
    """获取全局 CompilerContext

    首次调用时自动创建，后续复用同一实例。
    """
    global _global_context
    if _global_context is None:
        import catseq_rs
        _global_context = catseq_rs.CompilerContext()
    return _global_context


def clear_context() -> None:
    """清空全局上下文

    警告：清空后，之前创建的所有 node_id 将失效！
    """
    global _global_context
    if _global_context is not None:
        _global_context.clear()


def reset_context() -> None:
    """重置全局上下文（创建新实例）

    比 clear_context() 更彻底，释放旧内存。
    """
    global _global_context
    _global_context = None


def node_count() -> int:
    """获取当前上下文中的节点数量"""
    if _global_context is None:
        return 0
    return _global_context.node_count()


# Type aliases for flatten_by_board return structure
from typing import TypeAlias

TimelineEvent: TypeAlias = tuple[int, int, int, int, bytes]
"""(time, duration, channel_id, opcode, payload)"""

BoardTimeline: TypeAlias = tuple[int, int, list[TimelineEvent]]
"""(board_id, total_duration, events)"""


def flatten_by_board(node_id: int) -> list[BoardTimeline]:
    """按板卡展平 Morphism 树为时间线。

    DFS 遍历 Morphism Arena，合并同板卡所有通道事件，按时间排序。

    Args:
        node_id: 根节点 ID。

    Returns:
        板卡时间线列表，每个元素为:
        (board_id, total_duration, [
            (time, duration, channel_id, opcode, payload), ...
        ])
    """
    ctx = get_context()
    return ctx.flatten_by_board(node_id)


def _format_cycles(cycles: int) -> str:
    """将时钟周期格式化为人类可读的时间字符串"""
    seconds = cycles / CLOCK_FREQ_HZ
    if seconds == 0:
        return "0"
    elif seconds >= 1e-3:
        return f"{seconds * 1e3:.3g}ms"
    elif seconds >= 1e-6:
        return f"{seconds * 1e6:.3g}us"
    else:
        return f"{seconds * 1e9:.3g}ns"


def _opcode_name(opcode: int) -> str:
    """将 opcode 转为可读名称"""
    try:
        return OpCode(opcode).name
    except ValueError:
        return f"0x{opcode:04X}"


def _format_channel(channel_id: int) -> str:
    """将 channel_id 解码为 board:local 格式"""
    board = channel_id >> 16
    local = channel_id & 0xFFFF
    return f"B{board}:ch{local}"


def print_timeline(boards: list[BoardTimeline]) -> None:
    """友好打印 flatten_by_board 的结果。

    Args:
        boards: flatten_by_board 的返回值。
    """
    for board_id, total_dur, events in sorted(boards, key=lambda x: x[0]):
        print(f"Board {board_id}  (total: {_format_cycles(total_dur)})")
        print(f"  {'time':>10}  {'dur':>10}  {'channel':>8}  {'opcode':<20}  payload")
        print(f"  {'─'*10}  {'─'*10}  {'─'*8}  {'─'*20}  {'─'*16}")
        for time, dur, ch_id, opcode, payload in events:
            t_str = _format_cycles(time)
            d_str = _format_cycles(dur)
            ch_str = _format_channel(ch_id)
            op_str = _opcode_name(opcode)
            pay_str = payload.hex() if payload else ""
            print(f"  {t_str:>10}  {d_str:>10}  {ch_str:>8}  {op_str:<20}  {pay_str}")
        print()


# =============================================================================
# ProgramArena - 用于 Program DSL 控制流
# =============================================================================

# 使用 ContextVar 支持异步上下文隔离
_arena_context: ContextVar["catseq_rs.ProgramArena | None"] = ContextVar(
    "program_arena", default=None
)


def get_arena() -> "catseq_rs.ProgramArena":
    """获取当前 ProgramArena (惰性初始化)

    首次调用时自动创建，后续复用同一实例。
    支持 ContextVar，可用于异步场景的上下文隔离。
    """
    arena = _arena_context.get()
    if arena is None:
        import catseq_rs
        arena = catseq_rs.ProgramArena()
        _arena_context.set(arena)
    return arena


def reset_arena() -> None:
    """重置 ProgramArena（创建新实例）

    警告：重置后，之前创建的所有 NodeId/ValueId 将失效！
    """
    import catseq_rs
    _arena_context.set(catseq_rs.ProgramArena())


def clear_arena() -> None:
    """清空 ProgramArena（复用同一实例）

    比 reset_arena() 更轻量，不重新分配内存。
    """
    arena = _arena_context.get()
    if arena is not None:
        arena.clear()


def arena_node_count() -> int:
    """获取 ProgramArena 中的节点数量"""
    arena = _arena_context.get()
    if arena is None:
        return 0
    return arena.node_count()


def arena_value_count() -> int:
    """获取 ProgramArena 中的 Value 数量"""
    arena = _arena_context.get()
    if arena is None:
        return 0
    return arena.value_count()
