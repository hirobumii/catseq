"""
TTL hardware abstraction layer.

This module provides TTL-specific hardware abstractions and utilities
for working with TTL devices in the CatSeq framework.
"""

from ..types.common import Channel, State
from ..atomic import ttl_init, ttl_on, ttl_off
from ..morphism import identity, Morphism, MorphismDef
from ..time_utils import us_to_cycles, cycles_to_us


def pulse(channel: Channel, duration_us: float) -> Morphism:
    """创建 TTL 脉冲序列：ON → wait → OFF

    脉冲的总时长（从ON指令发出到OFF指令发出）等于指定的 duration_us。
    框架会自动减去 on_op 的执行开销。
    """
    on_op = ttl_on(channel)
    off_op = ttl_off(channel)

    # 用户的意图是 on 指令发出到 off 指令发出的总时长
    total_duration_cycles = us_to_cycles(duration_us)

    # 减去 on_op 的执行开销，得到实际的 wait 时长
    wait_duration_cycles = total_duration_cycles - on_op.total_duration_cycles

    if wait_duration_cycles < 0:
        raise ValueError(
            f"Pulse duration ({duration_us}μs) is too short to accommodate "
            f"the 'on' instruction cost ({cycles_to_us(on_op.total_duration_cycles)}μs)."
        )

    wait_op = identity(cycles_to_us(wait_duration_cycles))

    return on_op >> wait_op >> off_op


def initialize_channel(channel: Channel) -> Morphism:
    """初始化 TTL 通道到 OFF 状态
    
    Args:
        channel: 目标通道
        
    Returns:
        初始化 Morphism
    """
    return ttl_init(channel)


def set_high(channel: Channel) -> Morphism:
    """将 TTL 通道设为高电平
    
    Args:
        channel: 目标通道
        
    Returns:
        设置高电平的 Morphism
    """
    return ttl_on(channel)


def set_low(channel: Channel) -> Morphism:
    """将 TTL 通道设为低电平
    
    Args:
        channel: 目标通道
        
    Returns:
        设置低电平的 Morphism
    """
    return ttl_off(channel)


def hold(duration_us: float) -> MorphismDef:
    """Creates a definition for a hold (wait) operation."""

    def generator(channel: Channel, start_state: State) -> Morphism:
        return identity(duration_us)

    return MorphismDef(generator)


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
