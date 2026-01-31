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

class TTLUninitialized(HardwareState):
    def is_compatible_with(self, other: HardwareState) -> bool:
        return isinstance(other, TTLOff)


def ttl_init() -> OpenMorphism:
    """TTL 初始化 (原子操作)

    状态转换: TTLUninitialized -> TTLOff
    """
    def gen():
        yield (0, OpCode.TTL_INIT, b"")
    return OpenMorphism(gen, name="ttl_init", transitions={TTLUninitialized: TTLOff},
                        infer_state=lambda _: TTLOff())


def ttl_on() -> OpenMorphism:
    """TTL 开 (原子操作)

    状态转换: TTLOff -> TTLOn
    """
    def gen():
        yield (0, OpCode.TTL_ON, b"")
    return OpenMorphism(gen, name="ttl_on", transitions={TTLOff: TTLOn},
                        infer_state=lambda _: TTLOn())


def ttl_off() -> OpenMorphism:
    """TTL 关 (原子操作)

    状态转换: TTLOn -> TTLOff
    """
    def gen():
        yield (0, OpCode.TTL_OFF, b"")
    return OpenMorphism(gen, name="ttl_off", transitions={TTLOn: TTLOff},
                        infer_state=lambda _: TTLOff())


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



