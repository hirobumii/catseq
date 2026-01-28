"""CatSeq V2 TTL Operations - Compositional Architecture

基于原子操作的组合设计：
- 原子操作：ttl_init, ttl_set_on, ttl_set_off, wait
- 高层操作通过 >> 组合原子操作实现

使用示例：
    >>> from catseq.v2.ttl import ttl_on, ttl_off, ttl_pulse, wait
    >>> from catseq.time_utils import us
    >>>
    >>> # 组合操作
    >>> seq = ttl_on() >> wait(10*us) >> ttl_off()
    >>>
    >>> # 绑定到通道
    >>> bound = seq(ch)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from catseq.types.common import Channel
from catseq.time_utils import time_to_cycles
from catseq.v2.morphism import (
    HardwareState,
    OpenMorphism,
    BoundMorphism,
)
from catseq.v2.opcodes import OpCode


# =============================================================================
# TTL Hardware States
# =============================================================================

@dataclass(frozen=True)
class TTLOff(HardwareState):
    def is_compatible_with(self, other: HardwareState) -> bool:
        return isinstance(other, (TTLOn, TTLOff))


@dataclass(frozen=True)
class TTLOn(HardwareState):
    def is_compatible_with(self, other: HardwareState) -> bool:
        return isinstance(other, (TTLOn, TTLOff))


# =============================================================================
# Atomic Operations (原子操作)
# =============================================================================

def ttl_init() -> OpenMorphism:
    """TTL 初始化 (原子操作)

    状态转换: Any -> TTLOff
    """
    def gen():
        yield (0, OpCode.TTL_INIT, b"")
    return OpenMorphism(gen, name="ttl_init")


def ttl_on() -> OpenMorphism:
    """TTL 开 (原子操作)

    状态转换: TTLOff -> TTLOn
    """
    def gen():
        yield (0, OpCode.TTL_ON, b"")
    return OpenMorphism(gen, name="ttl_on")


def ttl_off() -> OpenMorphism:
    """TTL 关 (原子操作)

    状态转换: TTLOn -> TTLOff
    """
    def gen():
        yield (0, OpCode.TTL_OFF, b"")
    return OpenMorphism(gen, name="ttl_off")


def wait(duration: float) -> OpenMorphism:
    """等待 (原子操作)

    Args:
        duration: 等待时长 (秒，SI 单位)
    """
    def gen():
        cycles = time_to_cycles(duration)
        if cycles > 0:
            yield (cycles, OpCode.IDENTITY, b"")
    return OpenMorphism(gen, name=f"wait({duration*1e6:.1f}us)")


# =============================================================================
# Composite Operations (组合操作)
# =============================================================================

def ttl_pulse(duration: float) -> OpenMorphism:
    """TTL 脉冲 (组合操作)

    等价于: ttl_on() >> wait(duration) >> ttl_off()

    Args:
        duration: 脉冲时长 (秒，SI 单位)
    """
    return ttl_on() >> wait(duration) >> ttl_off()


# =============================================================================
# Hybrid API (可选：支持直接绑定通道)
# =============================================================================

def on(channel: Channel | None = None) -> Union[OpenMorphism, BoundMorphism]:
    """TTL ON (Hybrid API)

    用法 A: on() -> OpenMorphism
    用法 B: on(channel) -> BoundMorphism
    """
    om = ttl_on()
    return om if channel is None else om(channel)


def off(channel: Channel | None = None) -> Union[OpenMorphism, BoundMorphism]:
    """TTL OFF (Hybrid API)

    用法 A: off() -> OpenMorphism
    用法 B: off(channel) -> BoundMorphism
    """
    om = ttl_off()
    return om if channel is None else om(channel)


def pulse(
    arg1: Union[Channel, float],
    arg2: float | None = None
) -> Union[OpenMorphism, BoundMorphism]:
    """TTL 脉冲 (Hybrid API)

    用法 A: pulse(duration) -> OpenMorphism
    用法 B: pulse(channel, duration) -> BoundMorphism
    """
    if isinstance(arg1, Channel):
        channel = arg1
        duration = arg2 if arg2 is not None else 0.0
        return ttl_pulse(duration)(channel)
    else:
        return ttl_pulse(float(arg1))
