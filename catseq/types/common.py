"""
Common, hardware-agnostic types for the CatSeq framework.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum, auto
from itertools import count
from typing import Callable

from ..expr import Expr

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

    def __post_init__(self):
        if self.local_id < 0:
            raise ValueError(f"Channel local_id must be non-negative, got {self.local_id}")

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


class TimingKind(Enum):
    DELAY = auto()
    EXACT_EVENT = auto()
    RELAXED_WORK = auto()
    TIMED_REGION = auto()


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
class DebugFrame:
    """Source frame attached to a debug breadcrumb."""

    file_path: str
    line_number: int
    function_name: str
    source_text: str | None = None

    def describe(self) -> str:
        return f"{self.file_path}:{self.line_number} in {self.function_name}()"


@dataclass(frozen=True)
class DebugBreadcrumb:
    """One immutable provenance step in an atomic morphism trace."""

    kind: str
    frame: DebugFrame | None = None
    compose_kind: str | None = None
    side: str | None = None
    compose_id: int | None = None
    channel_id: str | None = None
    generator_index: int | None = None
    label: str | None = None
    reason: str | None = None
    note: str | None = None

    def describe(self) -> str:
        if self.kind == "factory":
            return "factory"
        if self.kind == "deferred_def":
            return "deferred definition"
        if self.kind == "deferred_apply":
            return (
                f"deferred apply generator[{self.generator_index}]"
                f"{f' on {self.channel_id}' if self.channel_id is not None else ''}"
            )
        if self.kind == "compose":
            return (
                f"compose {self.compose_kind} {self.side}"
                f"{f' #{self.compose_id}' if self.compose_id is not None else ''}"
            )
        if self.kind == "dict_apply":
            return (
                f"dict apply"
                f"{f' to {self.channel_id}' if self.channel_id is not None else ''}"
                f"{f' #{self.compose_id}' if self.compose_id is not None else ''}"
            )
        if self.kind == "auto_generated":
            return (
                "auto generated"
                f"{f' ({self.reason})' if self.reason is not None else ''}"
            )
        if self.kind == "label":
            return f"label {self.label}" if self.label is not None else "label"
        return self.kind


_DEBUG_ID_COUNTER = count(1)


@dataclass(frozen=True)
class AtomicMorphism:
    """最小操作单元 (不可变)"""
    channel: Channel | None
    start_state: State | None  # Generic state
    end_state: State | None    # Generic state
    duration_cycles: int | Expr
    operation_type: OperationType
    timing_kind: TimingKind = TimingKind.EXACT_EVENT
    debug_trace: tuple[DebugBreadcrumb, ...] = field(default_factory=tuple, kw_only=True)
    debug_id: int = field(default=0, kw_only=True)

    def __post_init__(self):
        if not isinstance(self.duration_cycles, Expr) and self.duration_cycles < 0:
            raise ValueError("Duration must be non-negative")
        if self.debug_id == 0:
            object.__setattr__(self, "debug_id", next(_DEBUG_ID_COUNTER))

    @property
    def debug_origin(self) -> DebugFrame | None:
        for breadcrumb in reversed(self.debug_trace):
            if breadcrumb.frame is not None:
                return breadcrumb.frame
        return None

    def with_debug_trace(self, debug_trace: tuple[DebugBreadcrumb, ...]) -> AtomicMorphism:
        return replace(self, debug_trace=debug_trace)

    def append_debug_breadcrumb(self, breadcrumb: DebugBreadcrumb) -> AtomicMorphism:
        return replace(self, debug_trace=self.debug_trace + (breadcrumb,))

    def append_debug_breadcrumbs(
        self,
        breadcrumbs: tuple[DebugBreadcrumb, ...],
    ) -> AtomicMorphism:
        return replace(self, debug_trace=self.debug_trace + breadcrumbs)

    def with_states(
        self,
        start_state: State | None,
        end_state: State | None,
    ) -> AtomicMorphism:
        return replace(self, start_state=start_state, end_state=end_state)

    def with_channel_and_states(
        self,
        channel: Channel | None,
        start_state: State | None,
        end_state: State | None,
    ) -> AtomicMorphism:
        return replace(
            self,
            channel=channel,
            start_state=start_state,
            end_state=end_state,
        )
    
    def __str__(self):
        from ..time_utils import cycles_to_us
        duration_us = None if isinstance(self.duration_cycles, Expr) else cycles_to_us(self.duration_cycles)
        
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
        
        if duration_us is None:
            return f"{op_name}(expr)"
        if duration_us > 0:
            return f"{op_name}({duration_us:.1f}μs)"
        else:
            return op_name


@dataclass(frozen=True, kw_only=True)
class TimedRegion:
    """Concrete duration-bearing source primitive for opaque board-local execution regions."""
    channel: Channel | None
    start_state: State | None
    end_state: State | None
    duration_cycles: int
    board_funcs: dict[Board, Callable]
    metadata: dict = field(default_factory=dict)
    operation_type: OperationType = OperationType.OPAQUE_OASM_FUNC
    timing_kind: TimingKind = TimingKind.TIMED_REGION
    user_func: Callable | None = None
    user_args: tuple = ()
    user_kwargs: dict = field(default_factory=dict)
    debug_trace: tuple[DebugBreadcrumb, ...] = field(default_factory=tuple)
    debug_id: int = field(default=0)
    region_id: int = field(default=0)

    def __post_init__(self):
        if self.duration_cycles < 0:
            raise ValueError("Timed region duration must be non-negative")
        if self.debug_id == 0:
            object.__setattr__(self, "debug_id", next(_DEBUG_ID_COUNTER))
        if self.region_id == 0:
            object.__setattr__(self, "region_id", next(_DEBUG_ID_COUNTER))

    @property
    def debug_origin(self) -> DebugFrame | None:
        for breadcrumb in reversed(self.debug_trace):
            if breadcrumb.frame is not None:
                return breadcrumb.frame
        return None

    def with_debug_trace(self, debug_trace: tuple[DebugBreadcrumb, ...]) -> TimedRegion:
        return replace(self, debug_trace=debug_trace)

    def append_debug_breadcrumb(self, breadcrumb: DebugBreadcrumb) -> TimedRegion:
        return replace(self, debug_trace=self.debug_trace + (breadcrumb,))

    def append_debug_breadcrumbs(
        self,
        breadcrumbs: tuple[DebugBreadcrumb, ...],
    ) -> TimedRegion:
        return replace(self, debug_trace=self.debug_trace + breadcrumbs)

    def with_states(
        self,
        start_state: State | None,
        end_state: State | None,
    ) -> TimedRegion:
        return replace(self, start_state=start_state, end_state=end_state)

    def with_channel_and_states(
        self,
        channel: Channel | None,
        start_state: State | None,
        end_state: State | None,
    ) -> TimedRegion:
        return replace(
            self,
            channel=channel,
            start_state=start_state,
            end_state=end_state,
        )

    def __str__(self):
        from ..time_utils import cycles_to_us

        return f"timed_region({cycles_to_us(self.duration_cycles):.1f}μs)"


@dataclass(frozen=True, kw_only=True)
class BlackBoxAtomicMorphism(AtomicMorphism):
    """An atomic morphism that wraps a user-defined OASM function (black box)."""
    user_func: Callable
    user_args: tuple
    user_kwargs: dict
    metadata: dict = field(default_factory=dict)  # For storing additional information (loop count, type, etc.)
