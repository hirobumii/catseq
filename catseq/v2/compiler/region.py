"""
Prepared static region IR for dynamic Program emits.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from catseq.types.common import Board, Channel, OperationType
from catseq.v2.expr.types import StartStateMap, ValueLike
from catseq.v2.morphism import Morphism

from .values import collect_value_free_vars, dump_prepared_value, partially_prepare_value


@dataclass(frozen=True)
class PreparedAtomicOperation:
    channel: Channel
    operation_type: OperationType
    start_state: ValueLike
    end_state: ValueLike
    duration_cycles: int
    free_vars: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class PreparedTimedOperation:
    start_cycles: int
    operation: PreparedAtomicOperation


@dataclass(frozen=True)
class RegionNode:
    kind: str
    children: tuple[int, ...] = ()
    board: Board | None = None
    operation: PreparedAtomicOperation | None = None
    start_cycles: int = 0
    duration_cycles: int = 0
    free_vars: frozenset[str] = field(default_factory=frozenset)


class RegionArena:
    def __init__(self) -> None:
        self.nodes: dict[int, RegionNode] = {}
        self.next_id = 1

    def add(self, node: RegionNode) -> int:
        node_id = self.next_id
        self.next_id += 1
        self.nodes[node_id] = node
        return node_id

    def dump(self, root_id: int | tuple[int, ...]) -> dict[str, object]:
        dumped_nodes: dict[int, dict[str, object]] = {}
        for node_id, node in sorted(self.nodes.items()):
            dumped: dict[str, object] = {"kind": node.kind}
            if node.children:
                dumped["children"] = node.children
            if node.board is not None:
                dumped["board"] = node.board.id
            if node.operation is not None:
                dumped["operation"] = {
                    "operation_type": node.operation.operation_type.name,
                    "channel": node.operation.channel.global_id,
                    "start_state": dump_prepared_value(node.operation.start_state),
                    "end_state": dump_prepared_value(node.operation.end_state),
                    "duration_cycles": node.operation.duration_cycles,
                }
            if node.start_cycles:
                dumped["start_cycles"] = node.start_cycles
            if node.duration_cycles:
                dumped["duration_cycles"] = node.duration_cycles
            if node.free_vars:
                dumped["free_vars"] = tuple(sorted(node.free_vars))
            dumped_nodes[node_id] = dumped
        return {"root": root_id, "nodes": dumped_nodes}


@dataclass(frozen=True)
class PreparedRegion:
    arena: RegionArena
    root_id: int
    end_states: StartStateMap
    free_vars: frozenset[str]

    def dump(self) -> dict[str, object]:
        dumped = self.arena.dump(self.root_id)
        dumped["free_vars"] = tuple(sorted(self.free_vars))
        return dumped


def prepare_morphism_region(
    morphism: Morphism,
    start_states: StartStateMap | ValueLike | None = None,
    *,
    arena: RegionArena | None = None,
) -> PreparedRegion:
    normalized = morphism._normalize_start_states(start_states)
    timed_ops, end_states = _prepare_node(morphism, morphism._root_id, normalized, 0)
    target_arena = RegionArena() if arena is None else arena
    root_id, free_vars = _build_region_root(target_arena, timed_ops)
    return PreparedRegion(target_arena, root_id, end_states, free_vars)


def _prepare_node(
    morphism: Morphism,
    root_id: int,
    start_states: StartStateMap,
    start_cycles: int,
) -> tuple[list[PreparedTimedOperation], StartStateMap]:
    node = morphism._arena.nodes[root_id]
    if node.kind == "empty":
        return [], dict(start_states)
    if node.kind in {"atomic", "wait"}:
        return _prepare_atomic(node.atomic, start_states, start_cycles)
    if node.kind == "serial":
        timed_ops: list[PreparedTimedOperation] = []
        current_states = dict(start_states)
        current_start = start_cycles
        for child_id in node.children:
            child_ops, child_end_states = _prepare_node(morphism, child_id, current_states, current_start)
            timed_ops.extend(child_ops)
            current_states.update(child_end_states)
            current_start += morphism._compute_duration(child_id)
        return timed_ops, current_states
    if node.kind == "parallel":
        timed_ops: list[PreparedTimedOperation] = []
        end_states: StartStateMap = {}
        current_states = dict(start_states)
        for child_id in node.children:
            child_channels = morphism._collect_channels(child_id)
            child_starts = {
                channel: current_states[channel]
                for channel in child_channels
                if channel in current_states
            }
            child_ops, child_end_states = _prepare_node(morphism, child_id, child_starts, start_cycles)
            timed_ops.extend(child_ops)
            end_states.update(child_end_states)
        current_states.update(end_states)
        return timed_ops, current_states
    raise ValueError(f"Unknown morphism node kind during region preparation: {node.kind}")


def _prepare_atomic(
    atomic,
    start_states: StartStateMap,
    start_cycles: int,
) -> tuple[list[PreparedTimedOperation], StartStateMap]:
    if atomic is None or atomic.channel is None:
        raise ValueError("Prepared regions require concrete channels.")
    start_state = start_states.get(atomic.channel)
    if atomic.state_requirement is not None:
        if start_state is None or not isinstance(start_state, atomic.state_requirement):
            raise TypeError(
                f"Channel {atomic.channel.global_id} requires start state "
                f"{atomic.state_requirement}, got {type(start_state)}"
            )
    if atomic.end_state_factory is not None:
        prepared_end_state = partially_prepare_value(atomic.end_state_factory(start_state), start_state)
    elif atomic.end_state is None:
        prepared_end_state = start_state
    else:
        prepared_end_state = partially_prepare_value(atomic.end_state, start_state)
    free_vars = collect_value_free_vars(prepared_end_state)
    prepared_op = PreparedAtomicOperation(
        channel=atomic.channel,
        operation_type=atomic.operation_type,
        start_state=start_state,
        end_state=prepared_end_state,
        duration_cycles=atomic.duration_cycles,
        free_vars=free_vars,
    )
    return [PreparedTimedOperation(start_cycles, prepared_op)], {atomic.channel: prepared_end_state}


def _build_region_root(
    arena: RegionArena,
    timed_ops: list[PreparedTimedOperation],
) -> tuple[int, frozenset[str]]:
    ops_by_board: dict[Board, list[PreparedTimedOperation]] = {}
    free_vars: set[str] = set()
    for timed_op in timed_ops:
        ops_by_board.setdefault(timed_op.operation.channel.board, []).append(timed_op)
        free_vars.update(timed_op.operation.free_vars)

    region_ids: list[int] = []
    for board in sorted(ops_by_board, key=lambda item: item.id):
        timed_node_ids: list[int] = []
        board_free_vars: set[str] = set()
        for timed_op in sorted(
            ops_by_board[board],
            key=lambda item: (
                item.start_cycles,
                item.operation.channel.local_id,
                item.operation.operation_type.value,
            ),
        ):
            board_free_vars.update(timed_op.operation.free_vars)
            timed_node_ids.append(
                arena.add(
                    RegionNode(
                        kind="timed_op",
                        operation=timed_op.operation,
                        start_cycles=timed_op.start_cycles,
                        duration_cycles=timed_op.operation.duration_cycles,
                        free_vars=timed_op.operation.free_vars,
                    )
                )
            )
        region_ids.append(
            arena.add(
                RegionNode(
                    kind="board_region",
                    board=board,
                    children=tuple(timed_node_ids),
                    free_vars=frozenset(board_free_vars),
                )
            )
        )
    root_id = arena.add(RegionNode(kind="region_root", children=tuple(region_ids), free_vars=frozenset(free_vars)))
    return root_id, frozenset(free_vars)
