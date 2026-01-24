"""CatSeq V2 TTL Operations

TTL 原子操作的 OpenMorphism 工厂函数。

使用示例：
    >>> from catseq.v2.ttl import ttl_on, ttl_off, wait
    >>> from catseq.v2.open_morphism import Morphism
    >>> import catseq_rs
    >>>
    >>> ctx = catseq_rs.CompilerContext()
    >>> ch = Channel(Board("RWG_0"), 0, ChannelType.TTL)
    >>>
    >>> # 构建脉冲序列
    >>> pulse = ttl_on() >> wait(10e-6) >> ttl_off()
    >>>
    >>> # 物化
    >>> result = pulse(ctx, ch, TTLOff())
    >>> assert isinstance(result.end_state, TTLOff)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

import catseq_rs

from catseq.types.common import Channel
from catseq.time_utils import time_to_cycles
from catseq.v2.open_morphism import HardwareState, Morphism, OpenMorphism
from catseq.v2.opcodes import OpCode


# =============================================================================
# TTL Hardware States
# =============================================================================

@dataclass(frozen=True)
class TTLOff(HardwareState):
    """TTL 关闭状态"""

    def is_compatible_with(self, other: HardwareState) -> bool:
        return isinstance(other, (TTLOn, TTLOff))


@dataclass(frozen=True)
class TTLOn(HardwareState):
    """TTL 开启状态"""

    def is_compatible_with(self, other: HardwareState) -> bool:
        return isinstance(other, (TTLOn, TTLOff))


# =============================================================================
# Channel ID Encoding
# =============================================================================

def encode_channel_id(channel: Channel) -> int:
    """将 Channel 编码为 u32

    编码格式: board_id (高16位) | local_id (低16位)

    注意：这里简化处理，假设 board.id 是 "RWG_0" 这样的格式
    """
    # 从 board.id 提取数字（如 "RWG_0" -> 0）
    board_num = int(channel.board.id.split("_")[-1])
    return (board_num << 16) | channel.local_id


# =============================================================================
# TTL Factory Functions
# =============================================================================

def ttl_on() -> OpenMorphism:
    """创建 TTL ON 操作

    状态转换: TTLOff -> TTLOn

    Returns:
        OpenMorphism
    """
    def kleisli(
        ctx: catseq_rs.CompilerContext,
        channel: Channel,
        state: HardwareState,
    ) -> Morphism:
        if not isinstance(state, TTLOff):
            raise TypeError(f"ttl_on() 需要 TTLOff 状态，得到 {type(state).__name__}")

        channel_id = encode_channel_id(channel)
        # Payload: 空（TTL ON 不需要额外参数）
        # duration = 0：瞬时操作
        node = ctx.atomic(channel_id, 0, OpCode.TTL_ON, b"")

        return Morphism(node.node_id, TTLOn())

    return OpenMorphism(kleisli, name="ttl_on")


def ttl_off() -> OpenMorphism:
    """创建 TTL OFF 操作

    状态转换: TTLOn -> TTLOff

    Returns:
        OpenMorphism
    """
    def kleisli(
        ctx: catseq_rs.CompilerContext,
        channel: Channel,
        state: HardwareState,
    ) -> Morphism:
        if not isinstance(state, TTLOn):
            raise TypeError(f"ttl_off() 需要 TTLOn 状态，得到 {type(state).__name__}")

        channel_id = encode_channel_id(channel)
        # duration = 0：瞬时操作
        node = ctx.atomic(channel_id, 0, OpCode.TTL_OFF, b"")

        return Morphism(node.node_id, TTLOff())

    return OpenMorphism(kleisli, name="ttl_off")


def wait(duration: float) -> OpenMorphism:
    """创建等待操作

    状态转换: S -> S（保持当前状态）

    Args:
        duration: 等待时间（秒，SI 单位）

    Returns:
        OpenMorphism
    """
    cycles = time_to_cycles(duration)

    def kleisli(
        ctx: catseq_rs.CompilerContext,
        channel: Channel,
        state: HardwareState,
    ) -> Morphism:
        channel_id = encode_channel_id(channel)
        # Payload: 空（等待不需要额外参数，时长已在 duration 中）
        node = ctx.atomic(channel_id, cycles, OpCode.IDENTITY, b"")

        # 保持当前状态
        return Morphism(node.node_id, state)

    return OpenMorphism(kleisli, name=f"wait({duration*1e6:.1f}μs)")


def ttl_init() -> OpenMorphism:
    """创建 TTL 初始化操作

    状态转换: Any -> TTLOff

    Returns:
        OpenMorphism
    """
    def kleisli(
        ctx: catseq_rs.CompilerContext,
        channel: Channel,
        state: HardwareState,
    ) -> Morphism:
        channel_id = encode_channel_id(channel)
        # duration = 0：瞬时操作
        node = ctx.atomic(channel_id, 0, OpCode.TTL_INIT, b"")

        return Morphism(node.node_id, TTLOff())

    return OpenMorphism(kleisli, name="ttl_init")


# =============================================================================
# Convenience Composite Functions
# =============================================================================

def ttl_pulse(duration: float) -> OpenMorphism:
    """创建 TTL 脉冲序列

    等效于: ttl_on() >> wait(duration) >> ttl_off()

    状态转换: TTLOff -> TTLOff

    Args:
        duration: 脉冲持续时间（秒，SI 单位）

    Returns:
        OpenMorphism
    """
    return ttl_on() >> wait(duration) >> ttl_off()
