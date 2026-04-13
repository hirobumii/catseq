"""
Deferred morphism builders and application helpers.
"""

from __future__ import annotations

from typing import Callable, Dict, Self

from ..debug import capture_callsite
from ..lanes import Lane
from ..types.common import AtomicMorphism, Channel, DebugOrigin, OperationType, State
from ..types.rwg import RWGUninitialized
from .core import Morphism


class MorphismDef:
    """
    Represents a deferred-execution 'recipe' for a morphism.
    It wraps a generator function that produces a Morphism when provided
    with a channel and a starting state.
    """

    def __init__(
        self,
        generator: Callable[[Channel, State], Morphism] | None = None,
        generators: tuple[Callable[[Channel, State], Morphism], ...] | None = None,
        origins: tuple[DebugOrigin | None, ...] | None = None,
    ):
        if generators is not None:
            self._generators = generators
        elif generator is not None:
            self._generators = (generator,)
        else:
            self._generators = ()

        if origins is not None:
            self._origins = origins
        else:
            origin = capture_callsite(stacklevel=2)
            self._origins = tuple(origin for _ in self._generators)

    def __call__(self, target: "Channel | Morphism", start_state: "State | None" = None) -> Morphism:
        if isinstance(target, Channel):
            if start_state is None:
                start_state = RWGUninitialized()
            return self._execute_on_channel(target, start_state)

        if not hasattr(target, "lanes"):
            raise TypeError(f"Target must be Channel or Morphism, got {type(target)}")
        return _apply_deferred_operations(
            target,
            {channel: self for channel in target.lanes.keys()},
        )

    def __rshift__(self, other: Self) -> "MorphismDef":
        if not isinstance(other, MorphismDef):
            return NotImplemented
        return MorphismDef(
            generators=self._generators + other._generators,
            origins=self._origins + other._origins,
        )

    def _execute_on_channel(self, channel: Channel, start_state: State) -> Morphism:
        current_state = start_state
        operations = []
        for generator, origin in zip(self._generators, self._origins, strict=True):
            morphism_piece = generator(channel, current_state)
            if not morphism_piece.lanes:
                if morphism_piece.total_duration_cycles > 0:
                    operations.append(
                        AtomicMorphism(
                            channel=channel,
                            start_state=current_state,
                            end_state=current_state,
                            duration_cycles=morphism_piece.total_duration_cycles,
                            operation_type=OperationType.IDENTITY,
                            debug_origin=origin,
                        )
                    )
            else:
                channel_lane = morphism_piece.lanes.get(channel)
                if channel_lane is None:
                    raise ValueError(
                        f"Deferred morphism for {channel.global_id} did not contain the target channel"
                    )
                operations.extend(op.with_debug_origin(origin) for op in channel_lane.operations)
                current_state = channel_lane.effective_end_state or current_state
        if not operations:
            return Morphism(lanes={}, _duration_cycles=0)
        return Morphism({channel: Lane(tuple(operations))})


def _inferred_lane_end_state(lane: Lane) -> State:
    return lane.effective_end_state if lane.effective_end_state is not None else RWGUninitialized()


def _inferred_morphism_end_state(morphism: Morphism, channel: Channel, fallback: State) -> State:
    if channel not in morphism.lanes:
        return fallback
    return _inferred_lane_end_state(morphism.lanes[channel])


def _pad_channel_morphism(result_morphism: Morphism, channel: Channel, target_duration_cycles: int) -> Morphism:
    current_duration = result_morphism.total_duration_cycles
    if current_duration >= target_duration_cycles:
        return result_morphism
    padding_cycles = target_duration_cycles - current_duration
    end_state = _inferred_morphism_end_state(result_morphism, channel, RWGUninitialized())
    padding_op = AtomicMorphism(
        channel=channel,
        start_state=end_state,
        end_state=end_state,
        duration_cycles=padding_cycles,
        operation_type=OperationType.IDENTITY,
    )
    channel_lane = result_morphism.lanes.get(channel, Lane(()))
    return Morphism({channel: Lane(channel_lane.operations + (padding_op,))})


def _apply_deferred_operations(base_morphism: Morphism, channel_operations: Dict[Channel, MorphismDef]) -> Morphism:
    for channel in channel_operations.keys():
        if channel not in base_morphism.lanes:
            available_channels = [str(ch.global_id) for ch in base_morphism.lanes.keys()]
            raise ValueError(
                f"Channel {channel.global_id} not found in morphism. "
                f"Available channels: {available_channels}"
            )

    if not channel_operations:
        return base_morphism

    operation_results: Dict[Channel, Morphism] = {}
    max_duration_cycles = 0
    for channel, operation_def in channel_operations.items():
        end_state = _inferred_morphism_end_state(base_morphism, channel, RWGUninitialized())
        result_morphism = operation_def(channel, end_state)
        operation_results[channel] = result_morphism
        max_duration_cycles = max(max_duration_cycles, result_morphism.total_duration_cycles)

    aligned_results = {
        channel: _pad_channel_morphism(result_morphism, channel, max_duration_cycles)
        for channel, result_morphism in operation_results.items()
    }

    new_lanes = {}
    for channel, lane in base_morphism.lanes.items():
        if channel in aligned_results:
            new_operations = lane.operations + aligned_results[channel].lanes[channel].operations
            new_lanes[channel] = Lane(new_operations)
        else:
            end_state = _inferred_lane_end_state(lane)
            wait_operation = AtomicMorphism(
                channel=channel,
                start_state=end_state,
                end_state=end_state,
                duration_cycles=max_duration_cycles,
                operation_type=OperationType.IDENTITY,
            )
            new_lanes[channel] = Lane(lane.operations + (wait_operation,))

    return Morphism(new_lanes)
