"""
Common, hardware-agnostic types for the CatSeq framework.
"""
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable

class ChannelType(Enum):
    """硬件通道类型"""
    TTL = auto()
    RWG = auto()

@dataclass(frozen=True)
class Board:
    """板卡标识符"""
    id: str

    def __str__(self):
        return self.id

@dataclass(frozen=True)
class Channel:
    """硬件通道标识符 (类型安全)"""
    board: Board
    local_id: int
    channel_type: ChannelType
    latency_cycles: int = 0  # 硬件触发延迟 (cycles)

    def __post_init__(self):
        if self.local_id < 0:
            raise ValueError(f"Channel local_id must be non-negative, got {self.local_id}")
        if self.latency_cycles < 0:
            raise ValueError(f"Channel latency_cycles must be non-negative, got {self.latency_cycles}")

    @property
    def global_id(self) -> str:
        """全局通道标识符"""
        return f"{self.board.id}_{self.channel_type.name}_{self.local_id}"

    def __str__(self):
        return self.global_id

class OperationType(Enum):
    """原子操作类型"""
    # 时间操作
    IDENTITY = auto()
    
    # TTL 操作
    TTL_INIT = auto()
    TTL_ON = auto()
    TTL_OFF = auto()

    # RWG 操作
    RWG_INIT = auto()
    RWG_SET_CARRIER = auto()
    RWG_LOAD_COEFFS = auto()
    RWG_UPDATE_PARAMS = auto()
    RWG_RF_SWITCH = auto()
    
    # 全局同步操作
    SYNC_MASTER = auto()
    SYNC_SLAVE = auto()

    # 黑盒操作
    OPAQUE_OASM_FUNC = auto()


TIMING_CRITICAL_OPERATIONS = {
    OperationType.IDENTITY,
    OperationType.TTL_ON,
    OperationType.TTL_OFF,
    OperationType.RWG_UPDATE_PARAMS,
    OperationType.RWG_RF_SWITCH,
    OperationType.SYNC_MASTER,
    OperationType.SYNC_SLAVE,
    OperationType.OPAQUE_OASM_FUNC, # Black boxes are critical by definition
}
"""Set of operations that must be executed at their precise timestamp."""

TIMING_NON_CRITICAL_OPERATIONS = {
    OperationType.TTL_INIT,
    OperationType.RWG_INIT,
    OperationType.RWG_SET_CARRIER,
    OperationType.RWG_LOAD_COEFFS,
}
"""Set of operations that can be rescheduled by the compiler for optimization."""


# A generic base class for all hardware states.
class State:
    pass


@dataclass(frozen=True)
class AtomicMorphism:
    """最小操作单元 (不可变)"""
    channel: Channel | None
    start_state: State | None  # Generic state
    end_state: State | None    # Generic state
    duration_cycles: int
    operation_type: OperationType

    def __post_init__(self):
        if self.duration_cycles < 0:
            raise ValueError("Duration must be non-negative")
    
    def __str__(self):
        from ..time_utils import cycles_to_us
        duration_us = cycles_to_us(self.duration_cycles)
        
        # 简化操作类型显示
        op_name = {
            OperationType.TTL_INIT: "ttl_init",
            OperationType.TTL_ON: "ttl_on", 
            OperationType.TTL_OFF: "ttl_off",
            OperationType.RWG_INIT: "rwg_init",
            OperationType.RWG_SET_CARRIER: "set_carrier",
            OperationType.RWG_LOAD_COEFFS: "load_coeffs",
            OperationType.RWG_UPDATE_PARAMS: "update_params",
            OperationType.RWG_RF_SWITCH: "rf_switch",
            OperationType.IDENTITY: "wait",
            OperationType.SYNC_MASTER: "sync_master",
            OperationType.SYNC_SLAVE: "sync_slave",
            OperationType.OPAQUE_OASM_FUNC: "opaque_oasm_func",
        }.get(self.operation_type, str(self.operation_type))
        
        if duration_us > 0:
            return f"{op_name}({duration_us:.1f}μs)"
        else:
            return op_name


@dataclass(frozen=True)
class BlackBoxAtomicMorphism(AtomicMorphism):
    """An atomic morphism that wraps a user-defined OASM function (black box)."""
    user_func: Callable
    user_args: tuple
    user_kwargs: dict
    metadata: dict = field(default_factory=dict)  # For storing additional information (loop count, type, etc.)
