"""
Core Morphism type and basic constructors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from ..debug import (
    annotate_morphism,
    auto_generated_breadcrumb,
    compose_breadcrumb,
    dict_apply_breadcrumb,
    next_compose_id,
)
from ..lanes import Lane
from ..time_utils import cycles_to_time, cycles_to_us, time_to_cycles, us
from ..types.common import AtomicMorphism, Board, Channel, DebugBreadcrumb, OperationType
from .views import lanes_view as render_lanes_view
from .views import morphism_str, timeline_view as render_timeline_view


@dataclass(frozen=True)
class Morphism:
    """组合 Morphism - 多通道操作的集合"""

    lanes: Dict[Channel, Lane]
    _duration_cycles: int = -1  # 内部使用，用于无通道的IdentityMorphism

    def __post_init__(self):
        """验证所有Lane的时长一致（Monoidal Category要求）"""
        if not self.lanes:
            if self._duration_cycles < 0:
                # This is a true empty morphism, which is fine.
                pass
            return

        reference_duration = next(iter(self.lanes.values())).total_duration_cycles
        mismatched_durations = [
            lane.total_duration_cycles
            for lane in self.lanes.values()
            if lane.total_duration_cycles != reference_duration
        ]
        if mismatched_durations:
            durations = [reference_duration, *mismatched_durations]
            duration_strs = [f"{cycles_to_us(d):.1f}μs" for d in durations]
            raise ValueError(
                "All lanes must have equal duration for parallel composition. "
                f"Got: {duration_strs}"
            )
        object.__setattr__(self, "_duration_cycles", reference_duration)

    @property
    def total_duration_cycles(self) -> int:
        """总时长（时钟周期）"""
        return self._duration_cycles if self._duration_cycles >= 0 else 0

    @property
    def total_duration_us(self) -> float:
        """总时长（微秒）- 使用SI单位系统"""
        return cycles_to_time(self.total_duration_cycles) / us

    def lanes_by_board(self) -> Dict[Board, Dict[Channel, Lane]]:
        """按板卡分组的通道-Lane映射"""
        result: Dict[Board, Dict[Channel, Lane]] = {}
        for channel, lane in self.lanes.items():
            board = channel.board
            if board not in result:
                result[board] = {}
            result[board][channel] = lane
        return result

    def __matmul__(self, other) -> "Morphism":
        """严格状态匹配组合操作符 @"""
        if isinstance(other, AtomicMorphism):
            other = from_atomic(other)
        from .compose import strict_compose_morphisms

        compose_id = next_compose_id()
        return strict_compose_morphisms(
            self,
            other,
            lhs_breadcrumb=compose_breadcrumb("strict", "lhs", compose_id, stacklevel=1),
            rhs_breadcrumb=compose_breadcrumb("strict", "rhs", compose_id, stacklevel=1),
        )

    def __rshift__(self, other) -> "Morphism":
        """自动状态推断组合操作符 >>"""
        if isinstance(other, AtomicMorphism):
            other = from_atomic(other)

        if isinstance(other, Morphism) and not other.lanes and other.total_duration_cycles > 0:
            compose_id = next_compose_id()
            lhs_breadcrumb = compose_breadcrumb("serial", "lhs", compose_id, stacklevel=1)
            rhs_breadcrumb = compose_breadcrumb("serial", "rhs", compose_id, stacklevel=1)
            if not self.lanes:
                return self if self.total_duration_cycles >= other.total_duration_cycles else other

            new_lanes = {}
            lhs = annotate_morphism(self, (lhs_breadcrumb,))
            for channel, lane in lhs.lanes.items():
                inferred_state = lane.effective_end_state
                if inferred_state is None and lane.initial_state is not None:
                    inferred_state = lane.initial_state

                identity_for_channel = AtomicMorphism(
                    channel=channel,
                    start_state=inferred_state,
                    end_state=inferred_state,
                    duration_cycles=other.total_duration_cycles,
                    operation_type=OperationType.IDENTITY,
                    debug_trace=(
                        auto_generated_breadcrumb("channelless_identity_expansion"),
                        rhs_breadcrumb,
                    ),
                )
                new_lanes[channel] = Lane(lane.operations + (identity_for_channel,))
            return Morphism(new_lanes)

        if isinstance(other, Morphism):
            from .compose import auto_compose_morphisms

            compose_id = next_compose_id()
            return auto_compose_morphisms(
                self,
                other,
                lhs_breadcrumb=compose_breadcrumb("serial", "lhs", compose_id, stacklevel=1),
                rhs_breadcrumb=compose_breadcrumb("serial", "rhs", compose_id, stacklevel=1),
            )

        from .deferred import MorphismDef

        if isinstance(other, MorphismDef):
            compose_id = next_compose_id()
            lhs = annotate_morphism(
                self,
                (compose_breadcrumb("serial", "lhs", compose_id, stacklevel=1),),
            )
            return other(
                lhs,
                application_breadcrumb=compose_breadcrumb(
                    "serial",
                    "rhs",
                    compose_id,
                    stacklevel=1,
                ),
            )

        if isinstance(other, dict):
            if not all(isinstance(k, Channel) for k in other.keys()):
                return NotImplemented
            if not all(isinstance(v, MorphismDef) for v in other.values()):
                return NotImplemented
            if not other:
                return self
            compose_id = next_compose_id()
            lhs = annotate_morphism(
                self,
                (compose_breadcrumb("serial", "lhs", compose_id, stacklevel=1),),
            )
            return lhs._apply_channel_operations(
                other,
                {
                    channel: (
                        dict_apply_breadcrumb(
                            channel.global_id,
                            compose_id,
                            stacklevel=1,
                        ),
                    )
                    for channel in other.keys()
                },
            )

        return NotImplemented

    def __or__(self, other) -> "Morphism":
        """并行组合操作符 |"""
        if isinstance(other, AtomicMorphism):
            other = from_atomic(other)
        from .compose import parallel_compose_morphisms

        compose_id = next_compose_id()
        return parallel_compose_morphisms(
            self,
            other,
            lhs_breadcrumb=compose_breadcrumb("parallel", "lhs", compose_id, stacklevel=1),
            rhs_breadcrumb=compose_breadcrumb("parallel", "rhs", compose_id, stacklevel=1),
        )

    def __str__(self):
        return morphism_str(self)

    def lanes_view(self) -> str:
        """生成详细的通道视图"""
        return render_lanes_view(self)

    def timeline_view(self, compact: bool = True) -> str:
        """生成时间轴视图，显示并行操作的时序关系"""
        return render_timeline_view(self, compact=compact)

    def _apply_channel_operations(
        self,
        channel_operations,
        application_breadcrumbs: Dict[Channel, tuple[DebugBreadcrumb, ...]] | None = None,
    ):
        from .deferred import _apply_deferred_operations

        return _apply_deferred_operations(self, channel_operations, application_breadcrumbs)


def from_atomic(op: AtomicMorphism) -> Morphism:
    """将原子操作转换为Morphism"""
    if op.channel is None:
        raise ValueError("Cannot create Morphism from an AtomicMorphism without a channel.")

    lane = Lane((op,))
    return Morphism({op.channel: lane})


def identity(duration: float) -> Morphism:
    """Creates a channelless identity morphism (a pure wait)."""
    duration_cycles = time_to_cycles(duration)
    if duration_cycles < 0:
        raise ValueError("Identity duration must be non-negative.")
    return Morphism(lanes={}, _duration_cycles=duration_cycles)
