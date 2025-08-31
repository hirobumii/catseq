"""
TTL hardware abstraction layer.

This module provides TTL-specific hardware abstractions and utilities
for working with TTL devices in the CatSeq framework.
"""

from ..types import Channel
from ..atomic import ttl_init, ttl_on, ttl_off, wait
from ..morphism import Morphism, from_atomic


def pulse(channel: Channel, duration_us: float) -> Morphism:
    """创建 TTL 脉冲序列：ON → wait → OFF
    
    Args:
        channel: 目标通道
        duration_us: 脉冲持续时间（微秒）
        
    Returns:
        脉冲 Morphism
    """
    on_op = ttl_on(channel)
    wait_op = wait(duration_us) 
    off_op = ttl_off(channel)
    
    return from_atomic(on_op) >> from_atomic(wait_op) >> from_atomic(off_op)


def initialize_channel(channel: Channel) -> Morphism:
    """初始化 TTL 通道到 OFF 状态
    
    Args:
        channel: 目标通道
        
    Returns:
        初始化 Morphism
    """
    return from_atomic(ttl_init(channel))


def set_high(channel: Channel) -> Morphism:
    """将 TTL 通道设为高电平
    
    Args:
        channel: 目标通道
        
    Returns:
        设置高电平的 Morphism
    """
    return from_atomic(ttl_on(channel))


def set_low(channel: Channel) -> Morphism:
    """将 TTL 通道设为低电平
    
    Args:
        channel: 目标通道
        
    Returns:
        设置低电平的 Morphism
    """
    return from_atomic(ttl_off(channel))


def hold(duration_us: float) -> Morphism:
    """创建等待操作
    
    Args:
        duration_us: 等待时长（微秒）
        
    Returns:
        等待 Morphism
    """
    return from_atomic(wait(duration_us))