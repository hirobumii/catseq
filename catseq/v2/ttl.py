"""CatSeq V2 TTL Operations - Hybrid Architecture

实现了 API 重载策略：
1. 模版模式 (Template Mode): 不传 channel，返回 OpenMorphism (蓝图)。
2. 构建模式 (Build Mode): 传入 channel，返回 BoundMorphism (预制件)。

使用示例：
    >>> from catseq.v2.ttl import ttl_pulse, ttl_on, TTLOff
    >>> from catseq.types.common import Channel
    >>>
    >>> # 用法 A: 直接构建 (推荐用于具体实验脚本)
    >>> bound = ttl_pulse(ch, 10e-6)
    >>>
    >>> # 用法 B: 定义模版 (推荐用于通用库函数)
    >>> template = ttl_pulse(10e-6)
    >>> bound = template(ch)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import overload, Union

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
# Data Generators (Pure Logic)
# =============================================================================
# 提取纯数据生成逻辑，供 OpenMorphism 复用
# Yields: (duration_cycles, opcode, payload_bytes)

def _gen_ttl_on():
    yield (0, OpCode.TTL_ON, b"")


def _gen_ttl_off():
    yield (0, OpCode.TTL_OFF, b"")


def _gen_wait(duration: float):
    cycles = time_to_cycles(duration)
    if cycles > 0:
        yield (cycles, OpCode.IDENTITY, b"")


def _gen_ttl_init():
    yield (0, OpCode.TTL_INIT, b"")


def _gen_ttl_pulse(duration: float):
    yield from _gen_ttl_on()
    yield from _gen_wait(duration)
    yield from _gen_ttl_off()


# =============================================================================
# Hybrid API Implementation
# =============================================================================

# --- 1. TTL ON ---

@overload
def ttl_on() -> OpenMorphism: ...
@overload
def ttl_on(channel: Channel) -> BoundMorphism: ...


def ttl_on(channel: Channel | None = None) -> Union[OpenMorphism, BoundMorphism]:
    """创建 TTL ON 操作 (Hybrid)

    Args:
        channel: 目标通道（可选）
            - 不传: 返回 OpenMorphism (模版)
            - 传入: 返回 BoundMorphism (已绑定)

    Returns:
        OpenMorphism 或 BoundMorphism
    """
    om = OpenMorphism(_gen_ttl_on, name="ttl_on")
    return om if channel is None else om(channel)


# --- 2. TTL OFF ---

@overload
def ttl_off() -> OpenMorphism: ...
@overload
def ttl_off(channel: Channel) -> BoundMorphism: ...


def ttl_off(channel: Channel | None = None) -> Union[OpenMorphism, BoundMorphism]:
    """创建 TTL OFF 操作 (Hybrid)"""
    om = OpenMorphism(_gen_ttl_off, name="ttl_off")
    return om if channel is None else om(channel)


# --- 3. WAIT ---

@overload
def wait(duration: float) -> OpenMorphism: ...
@overload
def wait(channel: Channel, duration: float) -> BoundMorphism: ...


def wait(
    arg1: Union[Channel, float],
    arg2: float | None = None
) -> Union[OpenMorphism, BoundMorphism]:
    """创建等待操作 (Hybrid)

    Args:
        用法 A: wait(duration) -> OpenMorphism
        用法 B: wait(channel, duration) -> BoundMorphism
    """
    # 识别参数模式
    if isinstance(arg1, Channel):
        # wait(channel, duration) -> BoundMorphism
        channel = arg1
        duration = arg2 if arg2 is not None else 0.0

        def gen():
            return _gen_wait(duration)

        om = OpenMorphism(gen, name=f"wait({duration*1e6:.1f}us)")
        return om(channel)
    else:
        # wait(duration) -> OpenMorphism
        duration = float(arg1)

        def gen():
            return _gen_wait(duration)

        return OpenMorphism(gen, name=f"wait({duration*1e6:.1f}us)")


# --- 4. TTL PULSE (Composite) ---

@overload
def ttl_pulse(duration: float) -> OpenMorphism: ...
@overload
def ttl_pulse(channel: Channel, duration: float) -> BoundMorphism: ...


def ttl_pulse(
    arg1: Union[Channel, float],
    arg2: float | None = None
) -> Union[OpenMorphism, BoundMorphism]:
    """创建 TTL 脉冲 (Hybrid Composite)

    等价于 ttl_on() >> wait(duration) >> ttl_off()
    """
    # 识别参数模式
    if isinstance(arg1, Channel):
        # ttl_pulse(channel, duration) -> BoundMorphism
        channel = arg1
        duration = arg2 if arg2 is not None else 0.0

        def gen():
            return _gen_ttl_pulse(duration)

        om = OpenMorphism(gen, name=f"ttl_pulse({duration*1e6:.1f}us)")
        return om(channel)
    else:
        # ttl_pulse(duration) -> OpenMorphism
        duration = float(arg1)

        def gen():
            return _gen_ttl_pulse(duration)

        return OpenMorphism(gen, name=f"ttl_pulse({duration*1e6:.1f}us)")


# --- 5. TTL INIT ---

@overload
def ttl_init() -> OpenMorphism: ...
@overload
def ttl_init(channel: Channel) -> BoundMorphism: ...


def ttl_init(channel: Channel | None = None) -> Union[OpenMorphism, BoundMorphism]:
    """创建 TTL 初始化操作 (Hybrid)

    通常用于序列开头，强制将状态置为 TTLOff。
    状态转换: Any -> TTLOff
    """
    om = OpenMorphism(_gen_ttl_init, name="ttl_init")
    return om if channel is None else om(channel)
