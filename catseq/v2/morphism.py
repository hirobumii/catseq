"""
Unified algebraic Morphism for CatSeq V2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from catseq.lanes import Lane
from catseq.morphism import Morphism as LegacyMorphism
from catseq.time_utils import cycles_to_time, cycles_to_us, time_to_cycles, us
from catseq.types.common import AtomicMorphism, Channel, OperationType, State

from .realize import realize_value
from .typing import EndStateFactory, StartStateMap, ValueLike


@dataclass(frozen=True)
class AtomicSpec:
    operation_type: OperationType
    channel: Channel | None
    duration_cycles: int
    state_requirement: type | tuple[type, ...] | None = None
    end_state: ValueLike = None
    end_state_factory: EndStateFactory | None = None


@dataclass(frozen=True)
class Node:
    kind: str
    children: tuple[int, ...] = ()
    atomic: AtomicSpec | None = None
    duration_cycles: int = 0


class Arena:
    def __init__(self):
        self.nodes: dict[int, Node] = {}
        self.next_id = 1

    def add(self, node: Node) -> int:
        node_id = self.next_id
        self.next_id += 1
        self.nodes[node_id] = node
        return node_id


@dataclass(frozen=True)
class _EvalResult:
    morphism: LegacyMorphism
    end_states: StartStateMap


class Morphism:
    __slots__ = ("_arena", "_root_id")

    def __init__(self, arena: Arena, root_id: int):
        self._arena = arena
        self._root_id = root_id

    @classmethod
    def empty(cls) -> Self:
        arena = Arena()
        return cls(arena, arena.add(Node("empty")))

    @classmethod
    def atomic(
        cls,
        operation_type: OperationType,
        *,
        channel: Channel | None = None,
        duration_cycles: int = 0,
        state_requirement: type | tuple[type, ...] | None = None,
        end_state: ValueLike = None,
        end_state_factory: EndStateFactory | None = None,
    ) -> Self:
        arena = Arena()
        root = arena.add(
            Node(
                "atomic",
                atomic=AtomicSpec(
                    operation_type=operation_type,
                    channel=channel,
                    duration_cycles=duration_cycles,
                    state_requirement=state_requirement,
                    end_state=end_state,
                    end_state_factory=end_state_factory,
                ),
                duration_cycles=duration_cycles,
            )
        )
        return cls(arena, root)

    @classmethod
    def wait(cls, duration: float, *, channel: Channel | None = None) -> Self:
        cycles = time_to_cycles(duration)
        arena = Arena()
        root = arena.add(
            Node(
                "wait",
                atomic=AtomicSpec(
                    operation_type=OperationType.IDENTITY,
                    channel=channel,
                    duration_cycles=cycles,
                ),
                duration_cycles=cycles,
            )
        )
        return cls(arena, root)

    @property
    def total_duration_cycles(self) -> int:
        return self._compute_duration(self._root_id)

    @property
    def total_duration_us(self) -> float:
        return cycles_to_time(self.total_duration_cycles) / us

    def __rshift__(self, other: Self) -> Self:
        if not isinstance(other, Morphism):
            return NotImplemented
        return self._compose("serial", other)

    def __or__(self, other: Self) -> Self:
        if not isinstance(other, Morphism):
            return NotImplemented
        return self._compose("parallel", other)

    def on(self, channel: Channel) -> Self:
        mapping, new_root = self._clone_arena()
        stack = [new_root]
        visited: set[int] = set()
        while stack:
            node_id = stack.pop()
            if node_id in visited:
                continue
            visited.add(node_id)
            node = mapping.nodes[node_id]
            if node.kind in {"atomic", "wait"} and node.atomic is not None and node.atomic.channel is None:
                new_atomic = AtomicSpec(
                    operation_type=node.atomic.operation_type,
                    channel=channel,
                    duration_cycles=node.atomic.duration_cycles,
                    state_requirement=node.atomic.state_requirement,
                    end_state=node.atomic.end_state,
                    end_state_factory=node.atomic.end_state_factory,
                )
                mapping.nodes[node_id] = Node(
                    kind=node.kind,
                    children=node.children,
                    atomic=new_atomic,
                    duration_cycles=node.duration_cycles,
                )
            stack.extend(node.children)
        return Morphism(mapping, new_root)

    def materialize(
        self,
        start_states: StartStateMap | State | ValueLike | None = None,
    ) -> LegacyMorphism:
        normalized = self._normalize_start_states(start_states)
        result = self._eval(self._root_id, normalized)
        return result.morphism

    def materialize_with_states(
        self,
        start_states: StartStateMap | State | ValueLike | None = None,
    ) -> tuple[LegacyMorphism, StartStateMap]:
        normalized = self._normalize_start_states(start_states)
        result = self._eval(self._root_id, normalized)
        return result.morphism, result.end_states

    def __str__(self) -> str:
        return f"V2Morphism(duration={cycles_to_us(self.total_duration_cycles):.1f}μs)"

    def _compose(self, kind: str, other: Self) -> Self:
        arena, left_root, right_root = self._merge_arenas(other)
        children = []
        left_node = arena.nodes[left_root]
        right_node = arena.nodes[right_root]
        if left_node.kind == kind:
            children.extend(left_node.children)
        else:
            children.append(left_root)
        if right_node.kind == kind:
            children.extend(right_node.children)
        else:
            children.append(right_root)
        root = arena.add(Node(kind, children=tuple(children)))
        return Morphism(arena, root)

    def _merge_arenas(self, other: Self) -> tuple[Arena, int, int]:
        arena = Arena()
        left_map = self._copy_into(arena, self._arena, self._root_id)
        right_map = self._copy_into(arena, other._arena, other._root_id)
        return arena, left_map[self._root_id], right_map[other._root_id]

    def _clone_arena(self) -> tuple[Arena, int]:
        arena = Arena()
        mapping = self._copy_into(arena, self._arena, self._root_id)
        return arena, mapping[self._root_id]

    @staticmethod
    def _copy_into(target: Arena, source: Arena, root_id: int) -> dict[int, int]:
        mapping: dict[int, int] = {}
        stack = [root_id]
        order: list[int] = []
        while stack:
            node_id = stack.pop()
            if node_id in mapping:
                continue
            mapping[node_id] = -1
            stack.extend(source.nodes[node_id].children)
            order.append(node_id)
        for old_id in reversed(order):
            node = source.nodes[old_id]
            children = tuple(mapping[child] for child in node.children)
            mapping[old_id] = target.add(
                Node(
                    kind=node.kind,
                    children=children,
                    atomic=node.atomic,
                    duration_cycles=node.duration_cycles,
                )
            )
        return mapping

    def _compute_duration(self, root_id: int) -> int:
        stack = [(root_id, False)]
        durations: dict[int, int] = {}
        while stack:
            node_id, expanded = stack.pop()
            node = self._arena.nodes[node_id]
            if expanded:
                if node.kind in {"empty", "atomic", "wait"}:
                    durations[node_id] = node.duration_cycles
                elif node.kind == "serial":
                    durations[node_id] = sum(durations[child] for child in node.children)
                elif node.kind == "parallel":
                    durations[node_id] = max((durations[child] for child in node.children), default=0)
                else:
                    raise ValueError(f"Unknown node kind: {node.kind}")
                continue
            stack.append((node_id, True))
            stack.extend((child, False) for child in node.children)
        return durations[root_id]

    def _normalize_start_states(
        self,
        start_states: StartStateMap | State | ValueLike | None,
    ) -> StartStateMap:
        if isinstance(start_states, dict):
            return start_states
        channels = self._channels()
        if start_states is None:
            return {}
        if len(channels) != 1:
            raise ValueError("A dict of start states is required for multi-channel morphisms.")
        return {next(iter(channels)): start_states}

    def _channels(self) -> set[Channel]:
        channels: set[Channel] = set()
        stack = [self._root_id]
        seen: set[int] = set()
        while stack:
            node_id = stack.pop()
            if node_id in seen:
                continue
            seen.add(node_id)
            node = self._arena.nodes[node_id]
            if node.atomic is not None and node.atomic.channel is not None:
                channels.add(node.atomic.channel)
            stack.extend(node.children)
        return channels

    def _eval(self, root_id: int, start_states: StartStateMap) -> _EvalResult:
        node = self._arena.nodes[root_id]
        if node.kind == "empty":
            return _EvalResult(LegacyMorphism(lanes={}, _duration_cycles=0), dict(start_states))
        if node.kind in {"atomic", "wait"}:
            return self._eval_atomic(node, start_states)
        if node.kind == "serial":
            current_states = dict(start_states)
            legacy = None
            for child in node.children:
                child_result = self._eval(child, current_states)
                legacy = child_result.morphism if legacy is None else legacy >> child_result.morphism
                current_states.update(child_result.end_states)
            return _EvalResult(
                legacy if legacy is not None else LegacyMorphism(lanes={}, _duration_cycles=0),
                current_states,
            )
        if node.kind == "parallel":
            current_states = dict(start_states)
            legacy = None
            end_states: StartStateMap = {}
            for child in node.children:
                child_channels = self._collect_channels(child)
                child_starts = {
                    ch: current_states[ch]
                    for ch in child_channels
                    if ch in current_states
                }
                child_result = self._eval(child, child_starts)
                legacy = child_result.morphism if legacy is None else legacy | child_result.morphism
                end_states.update(child_result.end_states)
            current_states.update(end_states)
            return _EvalResult(
                legacy if legacy is not None else LegacyMorphism(lanes={}, _duration_cycles=0),
                current_states,
            )
        raise ValueError(f"Unknown node kind: {node.kind}")

    def _collect_channels(self, root_id: int) -> set[Channel]:
        channels: set[Channel] = set()
        stack = [root_id]
        seen: set[int] = set()
        while stack:
            node_id = stack.pop()
            if node_id in seen:
                continue
            seen.add(node_id)
            node = self._arena.nodes[node_id]
            if node.atomic is not None and node.atomic.channel is not None:
                channels.add(node.atomic.channel)
            stack.extend(node.children)
        return channels

    def _eval_atomic(self, node: Node, start_states: StartStateMap) -> _EvalResult:
        assert node.atomic is not None
        channel = node.atomic.channel
        if channel is None:
            raise ValueError("Morphism must be bound to a concrete channel before materialization.")
        start_state = start_states.get(channel)
        if node.atomic.state_requirement is not None:
            if start_state is None or not isinstance(start_state, node.atomic.state_requirement):
                raise TypeError(
                    f"Channel {channel.global_id} requires start state "
                    f"{node.atomic.state_requirement}, got {type(start_state)}"
                )
        if node.atomic.end_state_factory is not None:
            resolved_end_state = node.atomic.end_state_factory(start_state)
        else:
            resolved_end_state = (
                start_state
                if node.atomic.end_state is None
                else realize_value(node.atomic.end_state, start_state)
            )
        op = AtomicMorphism(
            channel=channel,
            start_state=start_state,
            end_state=resolved_end_state,
            duration_cycles=node.atomic.duration_cycles,
            operation_type=node.atomic.operation_type,
        )
        legacy = LegacyMorphism({channel: Lane((op,))})
        return _EvalResult(legacy, {channel: resolved_end_state})
