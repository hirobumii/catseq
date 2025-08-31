"""
OASM interface type definitions.

This module defines the types used for interfacing with the OASM DSL,
including address enums, function enums, and call objects.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, Optional, Tuple

# Note: Actual functions are no longer imported here for OASMFunction definition
# They will be mapped in the compiler/executor.


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
    """OASM DSL 函数枚举 - 仅定义操作类型，不直接存储函数对象"""
    # TTL 函数
    TTL_CONFIG = auto()
    TTL_SET = auto()
    
    # 时间函数
    WAIT_US = auto()
    MY_WAIT = auto()
    
    # 触发函数
    TRIG_SLAVE = auto()


@dataclass(frozen=True)
class OASMCall:
    """OASM 调用对象 - 表示一个 seq() 调用"""
    adr: OASMAddress           # 目标地址
    dsl_func: OASMFunction     # DSL 函数 (现在是枚举成员)
    args: Tuple = ()           # 位置参数
    kwargs: Optional[Dict] = field(default_factory=dict)  # 关键字参数
    
    def __post_init__(self):
        # 确保 kwargs 不是 None
        if self.kwargs is None:
            object.__setattr__(self, 'kwargs', {})