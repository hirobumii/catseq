"""
Unified algebraic Morphism for CatSeq V2.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from catseq.time_utils import cycles_to_time, cycles_to_us, time_to_cycles, us
from catseq.types.common import AtomicMorphism, Channel, OperationType, State

from ..expr.realize import realize_value
from ..expr.types import EndStateFactory, StartStateMap, ValueLike


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
    def __init__(self) -> None:
        self.nodes: dict[int, Node] = {}
        self.next_id = 1

    def add(self, node: Node) -> int:
        node_id = self.next_id
        self.next_id += 1
        self.nodes[node_id] = node
        return node_id


@dataclass(frozen=True)
class RealizedNode:
    kind: str
    children: tuple[int, ...] = ()
    atomic: AtomicMorphism | None = None
    duration_cycles: int = 0


class RealizedArena:
    def __init__(self) -> None:
        self.nodes: dict[int, RealizedNode] = {}
        self.next_id = 1

    def add(self, node: RealizedNode) -> int:
        node_id = self.next_id
        self.next_id += 1
        self.nodes[node_id] = node
        return node_id


@dataclass(frozen=True)
class TimedAtomicOperation:
    start_cycles: int
    operation: AtomicMorphism


@dataclass(frozen=True)
class _MaterializeResult:
    morphism: RealizedMorphism
    end_states: StartStateMap


class RealizedMorphism:
    __slots__ = ("_arena", "_root_id")

    def __init__(self, arena: RealizedArena, root_id: int) -> None:
        self._arena = arena
        self._root_id = root_id

    @classmethod
    def empty(cls) -> Self:
        arena = RealizedArena()
        return cls(arena, arena.add(RealizedNode("empty")))

    @classmethod
    def atomic(cls, operation: AtomicMorphism) -> Self:
        arena = RealizedArena()
        root = arena.add(
            RealizedNode(
                "atomic",
                atomic=operation,
                duration_cycles=operation.duration_cycles,
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
        if not isinstance(other, RealizedMorphism):
            return NotImplemented
        return self._compose("serial", other)

    def __or__(self, other: Self) -> Self:
        if not isinstance(other, RealizedMorphism):
            return NotImplemented
        return self._compose("parallel", other)

    def timed_operations(self) -> tuple[TimedAtomicOperation, ...]:
        timed: list[TimedAtomicOperation] = []
        self._collect_timed_operations(self._root_id, 0, timed)
        return tuple(sorted(timed, key=lambda item: (item.start_cycles, item.operation.channel.global_id)))

    def arena_dump(self) -> dict[str, object]:
        dumped_nodes: dict[int, dict[str, object]] = {}
        for node_id, node in sorted(self._arena.nodes.items()):
            dumped: dict[str, object] = {"kind": node.kind}
            if node.children:
                dumped["children"] = node.children
            if node.atomic is not None:
                dumped["atomic"] = {
                    "operation_type": node.atomic.operation_type.name,
                    "channel": node.atomic.channel.global_id if node.atomic.channel is not None else None,
                    "duration_cycles": node.atomic.duration_cycles,
                    "start_state": repr(node.atomic.start_state),
                    "end_state": repr(node.atomic.end_state),
                }
            if node.duration_cycles:
                dumped["duration_cycles"] = node.duration_cycles
            dumped_nodes[node_id] = dumped
        return {"root": self._root_id, "nodes": dumped_nodes}

    def __str__(self) -> str:
        return f"RealizedV2Morphism(duration={cycles_to_us(self.total_duration_cycles):.1f}μs)"

    def _compose(self, kind: str, other: Self) -> Self:
        arena, left_root, right_root = self._merge_arenas(other)
        children: list[int] = []
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
        root = arena.add(RealizedNode(kind, children=tuple(children)))
        return RealizedMorphism(arena, root)

    def _merge_arenas(self, other: Self) -> tuple[RealizedArena, int, int]:
        arena = RealizedArena()
        left_map = self._copy_into(arena, self._arena, self._root_id)
        right_map = self._copy_into(arena, other._arena, other._root_id)
        return arena, left_map[self._root_id], right_map[other._root_id]

    @staticmethod
    def _copy_into(target: RealizedArena, source: RealizedArena, root_id: int) -> dict[int, int]:
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
                RealizedNode(
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
                    raise ValueError(f"Unknown realized node kind: {node.kind}")
                continue
            stack.append((node_id, True))
            stack.extend((child, False) for child in node.children)
        return durations[root_id]

    def _collect_timed_operations(
        self,
        root_id: int,
        start_cycles: int,
        timed: list[TimedAtomicOperation],
    ) -> None:
        node = self._arena.nodes[root_id]
        if node.kind == "empty":
            return
        if node.kind in {"atomic", "wait"}:
            if node.atomic is not None:
                timed.append(TimedAtomicOperation(start_cycles, node.atomic))
            return
        if node.kind == "serial":
            current_start = start_cycles
            for child in node.children:
                self._collect_timed_operations(child, current_start, timed)
                current_start += self._compute_duration(child)
            return
        if node.kind == "parallel":
            for child in node.children:
                self._collect_timed_operations(child, start_cycles, timed)
            return
        raise ValueError(f"Unknown realized node kind: {node.kind}")


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

    def materialize(self, start_states: StartStateMap | State | ValueLike | None = None) -> RealizedMorphism:
        normalized = self._normalize_start_states(start_states)
        result = self._materialize_with_env(normalized, None)
        return result.morphism

    def materialize_with_states(
        self,
        start_states: StartStateMap | State | ValueLike | None = None,
    ) -> tuple[RealizedMorphism, StartStateMap]:
        normalized = self._normalize_start_states(start_states)
        result = self._materialize_with_env(normalized, None)
        return result.morphism, result.end_states

    def arena_dump(self) -> dict[str, object]:
        dumped_nodes: dict[int, dict[str, object]] = {}
        for node_id, node in sorted(self._arena.nodes.items()):
            dumped: dict[str, object] = {"kind": node.kind}
            if node.children:
                dumped["children"] = node.children
            if node.atomic is not None:
                dumped["atomic"] = {
                    "operation_type": node.atomic.operation_type.name,
                    "channel": node.atomic.channel.global_id if node.atomic.channel is not None else None,
                    "duration_cycles": node.atomic.duration_cycles,
                    "state_requirement": (
                        None
                        if node.atomic.state_requirement is None
                        else repr(node.atomic.state_requirement)
                    ),
                    "end_state": repr(node.atomic.end_state),
                    "end_state_factory": (
                        None if node.atomic.end_state_factory is None else repr(node.atomic.end_state_factory)
                    ),
                }
            if node.duration_cycles:
                dumped["duration_cycles"] = node.duration_cycles
            dumped_nodes[node_id] = dumped
        return {"root": self._root_id, "nodes": dumped_nodes}

    def __str__(self) -> str:
        return f"V2Morphism(duration={cycles_to_us(self.total_duration_cycles):.1f}μs)"

    def _compose(self, kind: str, other: Self) -> Self:
        arena, left_root, right_root = self._merge_arenas(other)
        children: list[int] = []
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

    def _materialize_with_env(
        self,
        start_states: StartStateMap,
        runtime_env: Mapping[str, object] | None,
    ) -> _MaterializeResult:
        return self._eval(self._root_id, start_states, runtime_env)

    def _eval(
        self,
        root_id: int,
        start_states: StartStateMap,
        runtime_env: Mapping[str, object] | None,
    ) -> _MaterializeResult:
        node = self._arena.nodes[root_id]
        if node.kind == "empty":
            return _MaterializeResult(RealizedMorphism.empty(), dict(start_states))
        if node.kind in {"atomic", "wait"}:
            return self._eval_atomic(node, start_states, runtime_env)
        if node.kind == "serial":
            current_states = dict(start_states)
            realized = RealizedMorphism.empty()
            for child in node.children:
                child_result = self._eval(child, current_states, runtime_env)
                realized = realized >> child_result.morphism
                current_states.update(child_result.end_states)
            return _MaterializeResult(realized, current_states)
        if node.kind == "parallel":
            current_states = dict(start_states)
            realized = RealizedMorphism.empty()
            end_states: StartStateMap = {}
            for child in node.children:
                child_channels = self._collect_channels(child)
                child_starts = {channel: current_states[channel] for channel in child_channels if channel in current_states}
                child_result = self._eval(child, child_starts, runtime_env)
                realized = realized | child_result.morphism
                end_states.update(child_result.end_states)
            current_states.update(end_states)
            return _MaterializeResult(realized, current_states)
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

    def _eval_atomic(
        self,
        node: Node,
        start_states: StartStateMap,
        runtime_env: Mapping[str, object] | None,
    ) -> _MaterializeResult:
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
            resolved_end_state = realize_value(
                node.atomic.end_state_factory(start_state),
                start_state,
                runtime_env,
            )
        else:
            resolved_end_state = (
                start_state
                if node.atomic.end_state is None
                else realize_value(node.atomic.end_state, start_state, runtime_env)
            )
        realized_op = AtomicMorphism(
            channel=channel,
            start_state=start_state,
            end_state=resolved_end_state,
            duration_cycles=node.atomic.duration_cycles,
            operation_type=node.atomic.operation_type,
        )
        return _MaterializeResult(
            RealizedMorphism.atomic(realized_op),
            {channel: resolved_end_state},
        )
