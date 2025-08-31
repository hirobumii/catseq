"""
OASM interface type definitions.

This module defines the types used for interfacing with the OASM DSL,
including address enums, function enums, and call objects.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

from .functions import ttl_config, ttl_set, wait_us, my_wait, trig_slave


class OASMAddress(Enum):
    """OASM 地址枚举 - 对应硬件板卡地址"""
    MAIN = "main"
    RWG0 = "rwg0"
    RWG1 = "rwg1"
    RWG2 = "rwg2"
    RWG3 = "rwg3"
    RWG4 = "rwg4"
    RWG5 = "rwg5"
    RWG6 = "rwg6"
    RWG7 = "rwg7"


class OASMFunction(Enum):
    """OASM DSL 函数枚举 - 存储实际的函数对象"""
    # TTL 函数
    TTL_CONFIG = ttl_config  # TTL通道方向配置 (用于 TTL_INIT)
    TTL_SET = ttl_set        # TTL通道状态设置 (用于 TTL_ON/TTL_OFF)
    
    # 时间函数
    WAIT_US = wait_us
    MY_WAIT = my_wait
    
    # 触发函数
    TRIG_SLAVE = trig_slave


@dataclass(frozen=True)
class OASMCall:
    """OASM 调用对象 - 表示一个 seq() 调用"""
    adr: OASMAddress           # 目标地址
    dsl_func: OASMFunction     # DSL 函数
    args: Tuple = ()           # 位置参数
    kwargs: Optional[Dict] = field(default_factory=dict)  # 关键字参数
    
    def __post_init__(self):
        # 确保 kwargs 不是 None
        if self.kwargs is None:
            object.__setattr__(self, 'kwargs', {})