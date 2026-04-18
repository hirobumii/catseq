"""
TTL hardware abstraction layer.

This module provides TTL-specific hardware abstractions and utilities
for working with TTL devices in the CatSeq framework.
"""

from ..types.common import Channel, State, AtomicMorphism, OperationType
from ..atomic import ttl_init, ttl_on, ttl_off
from ..morphism import identity, Morphism, MorphismDef
from ..time_utils import us_to_cycles, cycles_to_us, time_to_cycles, cycles_to_time
from ..lanes import Lane
from .common import hold


def pulse(duration: float) -> MorphismDef:
    """创建 TTL 脉冲序列：ON → wait → OFF

    脉冲的总时长（从ON指令发出到OFF指令发出）等于指定的 duration。

    Args:
        duration: Pulse duration in seconds (SI unit)
    """

    def generator(channel: Channel, start_state: State) -> Morphism:
        on_op = ttl_on(channel)
        off_op = ttl_off(channel)
        wait_op = identity(duration)
        return on_op >> wait_op >> off_op

    return MorphismDef(generator)


def initialize() -> MorphismDef:
    """初始化 TTL 通道到 OFF 状态
    
    Returns:
        初始化 MorphismDef
    """
    
    def generator(channel: Channel, start_state: State) -> Morphism:
        return ttl_init(channel)

    return MorphismDef(generator)


def set_high() -> MorphismDef:
    """将 TTL 通道设为高电平
    
    Returns:
        设置高电平的 MorphismDef
    """
    
    def generator(channel: Channel, start_state: State) -> Morphism:
        return ttl_on(channel)

    return MorphismDef(generator)


def set_low() -> MorphismDef:
    """将 TTL 通道设为低电平
    
    Returns:
        设置低电平的 MorphismDef
    """
    
    def generator(channel: Channel, start_state: State) -> Morphism:
        return ttl_off(channel)

    return MorphismDef(generator)


# hold function is now imported from .common


def on() -> MorphismDef:
    """Creates a TTL ON morphism definition.
    The start state will be inferred during composition.
    """
    def generator(channel: Channel, start_state: State) -> Morphism:
        # This generator will be executed later.
        # It calls the low-level atomic function, passing the inferred start_state.
        return ttl_on(channel, start_state=start_state)
    return MorphismDef(generator)


def off() -> MorphismDef:
    """Creates a TTL OFF morphism definition.
    The start state will be inferred during composition.
    """
    def generator(channel: Channel, start_state: State) -> Morphism:
        # This generator will be executed later.
        # It calls the low-level atomic function, passing the inferred start_state.
        return ttl_off(channel, start_state=start_state)
    return MorphismDef(generator)
