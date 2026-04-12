"""
Static schedule arena for direct CatSeq v2 compilation.
"""

from __future__ import annotations

from dataclasses import dataclass

from catseq.types.common import AtomicMorphism, Board
from catseq.v2.morphism import Morphism, RealizedMorphism


@dataclass(frozen=True)
class ScheduleNode:
    kind: str
    children: tuple[int, ...] = ()
    board: Board | None = None
    operation: AtomicMorphism | None = None
    start_cycles: int = 0
    duration_cycles: int = 0


class ScheduleArena:
    def __init__(self) -> None:
        self.nodes: dict[int, ScheduleNode] = {}
        self.next_id = 1
        self.root_id: int | None = None

    def add(self, node: ScheduleNode) -> int:
        node_id = self.next_id
        self.next_id += 1
        self.nodes[node_id] = node
        return node_id

    def dump(self) -> dict[str, object]:
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
                    "channel": node.operation.channel.global_id if node.operation.channel is not None else None,
                    "start_state": repr(node.operation.start_state),
                    "end_state": repr(node.operation.end_state),
                }
            if node.start_cycles:
                dumped["start_cycles"] = node.start_cycles
            if node.duration_cycles:
                dumped["duration_cycles"] = node.duration_cycles
            dumped_nodes[node_id] = dumped
        return {"root": self.root_id, "nodes": dumped_nodes}


def lower_v2_morphism_to_schedule(
    morphism: Morphism | RealizedMorphism,
    start_states=None,
) -> ScheduleArena:
    realized = morphism if isinstance(morphism, RealizedMorphism) else morphism.materialize(start_states)

    ops_by_board: dict[Board, list[tuple[int, AtomicMorphism]]] = {}
    for timed_op in realized.timed_operations():
        if timed_op.operation.channel is None:
            continue
        board = timed_op.operation.channel.board
        ops_by_board.setdefault(board, []).append((timed_op.start_cycles, timed_op.operation))

    arena = ScheduleArena()
    region_ids: list[int] = []
    for board in sorted(ops_by_board, key=lambda item: item.id):
        op_ids: list[int] = []
        for start_cycles, operation in sorted(
            ops_by_board[board],
            key=lambda item: (
                item[0],
                item[1].channel.local_id if item[1].channel is not None else -1,
                item[1].operation_type.value,
            ),
        ):
            op_ids.append(
                arena.add(
                    ScheduleNode(
                        kind="timed_op",
                        operation=operation,
                        start_cycles=start_cycles,
                        duration_cycles=operation.duration_cycles,
                    )
                )
            )
        region_ids.append(arena.add(ScheduleNode(kind="board_region", board=board, children=tuple(op_ids))))
    arena.root_id = arena.add(ScheduleNode(kind="root", children=tuple(region_ids)))
    return arena
