"""
Lowered control IR for CatSeq v2 Program.
"""

from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass

from catseq.v2.expr import SymExpr
from catseq.v2.expr.types import StartStateMap, ValueLike
from catseq.v2.program.core import Call, Program, Select

from .region import RegionArena, prepare_morphism_region
from .values import collect_value_free_vars, dump_prepared_value, partially_prepare_value


class ProgramLoweringError(ValueError):
    pass


@dataclass(frozen=True)
class ControlNode:
    kind: str
    children: tuple[int, ...] = ()
    name: str | None = None
    source: ValueLike | None = None
    value: ValueLike | Select | None = None
    function: str | None = None
    args: tuple[ValueLike | Select, ...] = ()
    kwargs: tuple[tuple[str, ValueLike | Select], ...] = ()
    region_root: int | None = None
    then_block: int | None = None
    else_block: int | None = None
    target_block: int | None = None
    free_vars: frozenset[str] = field(default_factory=frozenset)


class ControlArena:
    def __init__(self) -> None:
        self.nodes: dict[int, ControlNode] = {}
        self.next_id = 1

    def add(self, node: ControlNode) -> int:
        node_id = self.next_id
        self.next_id += 1
        self.nodes[node_id] = node
        return node_id

    def dump(self, root_id: int) -> dict[str, object]:
        dumped_nodes: dict[int, dict[str, object]] = {}
        for node_id, node in sorted(self.nodes.items()):
            dumped: dict[str, object] = {"kind": node.kind}
            if node.children:
                dumped["children"] = node.children
            if node.name is not None:
                dumped["name"] = node.name
            if node.source is not None:
                dumped["source"] = _dump_control_value(node.source)
            if node.value is not None:
                dumped["value"] = _dump_control_value(node.value)
            if node.function is not None:
                dumped["function"] = node.function
            if node.args:
                dumped["args"] = tuple(_dump_control_value(arg) for arg in node.args)
            if node.kwargs:
                dumped["kwargs"] = tuple((key, _dump_control_value(value)) for key, value in node.kwargs)
            if node.region_root is not None:
                dumped["region_root"] = node.region_root
            if node.then_block is not None:
                dumped["then_block"] = node.then_block
            if node.else_block is not None:
                dumped["else_block"] = node.else_block
            if node.target_block is not None:
                dumped["target_block"] = node.target_block
            if node.free_vars:
                dumped["free_vars"] = tuple(sorted(node.free_vars))
            dumped_nodes[node_id] = dumped
        return {"root": root_id, "nodes": dumped_nodes}


@dataclass(frozen=True)
class ProgramIR:
    control_arena: ControlArena
    region_arena: RegionArena
    root_block_id: int

    def dump(self) -> dict[str, object]:
        return {
            "root_block": self.root_block_id,
            "control": self.control_arena.dump(self.root_block_id),
            "regions": self.region_arena.dump(self._find_region_roots()),
        }

    def _find_region_roots(self) -> int | tuple[int, ...]:
        region_roots = [
            node_id
            for node_id, node in self.region_arena.nodes.items()
            if node.kind == "region_root"
        ]
        if not region_roots:
            return 0
        if len(region_roots) == 1:
            return region_roots[0]
        return tuple(region_roots)


def lower_program_to_ir(
    program: Program,
    *,
    start_states: StartStateMap | ValueLike | None = None,
) -> ProgramIR:
    normalized = dict(start_states or {}) if isinstance(start_states, dict) else {}
    control_arena = ControlArena()
    region_arena = RegionArena()
    root_block_id, _ = _lower_block(program, program._root_id, control_arena, region_arena, normalized)
    return ProgramIR(control_arena, region_arena, root_block_id)


def _lower_block(
    program: Program,
    block_root_id: int,
    control_arena: ControlArena,
    region_arena: RegionArena,
    start_states: StartStateMap,
) -> tuple[int, StartStateMap]:
    block_node = program._arena.nodes[block_root_id]
    if block_node.kind != "seq":
        raise ProgramLoweringError("Program lowering expects sequence roots.")

    child_ids: list[int] = []
    current_states = dict(start_states)
    for index, statement_id in enumerate(block_node.children):
        statement = program._arena.nodes[statement_id]
        is_last = index == len(block_node.children) - 1

        if statement.kind == "measure":
            child_ids.append(control_arena.add(ControlNode("measure", name=statement.name, source=statement.source)))
            continue
        if statement.kind in {"let", "assign"}:
            lowered_value = _lower_control_value(statement.value)
            free_vars = _collect_control_free_vars(lowered_value)
            if isinstance(lowered_value, Call):
                if not isinstance(lowered_value.function, str):
                    raise ProgramLoweringError("Program IR lowering only supports string-named calls.")
                child_ids.append(
                    control_arena.add(
                        ControlNode(
                            "call",
                            name=statement.name,
                            function=lowered_value.function,
                            args=tuple(_lower_control_value(arg) for arg in lowered_value.args),
                            kwargs=tuple(
                                (key, _lower_control_value(value))
                                for key, value in lowered_value.kwargs
                            ),
                            free_vars=free_vars,
                        )
                    )
                )
                continue
            child_ids.append(
                control_arena.add(
                    ControlNode(
                        "assign",
                        name=statement.name,
                        value=lowered_value,
                        free_vars=free_vars,
                    )
                )
            )
            continue
        if statement.kind == "emit":
            if statement.morphism is None:
                raise ProgramLoweringError("Emit node is missing a source morphism.")
            prepared_region = prepare_morphism_region(statement.morphism, current_states, arena=region_arena)
            child_ids.append(
                control_arena.add(
                    ControlNode(
                        "emit_region",
                        region_root=prepared_region.root_id,
                        free_vars=prepared_region.free_vars,
                    )
                )
            )
            current_states.update(prepared_region.end_states)
            continue
        if statement.kind == "branch":
            if not is_last:
                raise ProgramLoweringError("Branch lowering currently requires branch to be terminal in its block.")
            if statement.then_root is None or statement.else_root is None:
                raise ProgramLoweringError("Branch node is missing one of its child blocks.")
            condition = _lower_control_value(statement.value)
            then_block_id, _ = _lower_block(
                program,
                statement.then_root,
                control_arena,
                region_arena,
                dict(current_states),
            )
            else_block_id, _ = _lower_block(
                program,
                statement.else_root,
                control_arena,
                region_arena,
                dict(current_states),
            )
            child_ids.append(
                control_arena.add(
                    ControlNode(
                        "branch",
                        value=condition,
                        then_block=then_block_id,
                        else_block=else_block_id,
                        free_vars=_collect_control_free_vars(condition),
                    )
                )
            )
            continue
        if statement.kind == "return":
            lowered_value = _lower_control_value(statement.value)
            child_ids.append(
                control_arena.add(
                    ControlNode(
                        "return",
                        value=lowered_value,
                        free_vars=_collect_control_free_vars(lowered_value),
                    )
                )
            )
            continue
        if statement.kind in {"for_range", "while", "function"}:
            raise ProgramLoweringError(f"Program IR lowering does not yet support {statement.kind}.")
        raise ProgramLoweringError(f"Unsupported lowered Program node kind: {statement.kind}.")

    return control_arena.add(ControlNode("block", children=tuple(child_ids))), current_states


def _lower_control_value(value: ValueLike | Call | Select | None) -> ValueLike | Call | Select | None:
    if value is None:
        return None
    if isinstance(value, Call):
        lowered_args = tuple(_lower_control_value(arg) for arg in value.args)
        lowered_kwargs = tuple((key, _lower_control_value(item)) for key, item in value.kwargs)
        return Call(value.function, lowered_args, lowered_kwargs)
    if isinstance(value, Select):
        condition = _lower_control_value(value.condition)
        then_value = _lower_control_value(value.then_value)
        else_value = _lower_control_value(value.else_value)
        return Select(condition, then_value, else_value)
    return partially_prepare_value(value, None)


def _collect_control_free_vars(value: ValueLike | Call | Select | None) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, Call):
        free_vars: set[str] = set()
        for arg in value.args:
            free_vars.update(_collect_control_free_vars(arg))
        for _, item in value.kwargs:
            free_vars.update(_collect_control_free_vars(item))
        return frozenset(free_vars)
    if isinstance(value, Select):
        free_vars: set[str] = set()
        free_vars.update(_collect_control_free_vars(value.condition))
        free_vars.update(_collect_control_free_vars(value.then_value))
        free_vars.update(_collect_control_free_vars(value.else_value))
        return frozenset(free_vars)
    return collect_value_free_vars(value)


def _dump_control_value(value: ValueLike | Call | Select) -> object:
    if isinstance(value, Call):
        return {
            "call": value.function if isinstance(value.function, str) else repr(value.function),
            "args": tuple(_dump_control_value(arg) for arg in value.args),
            "kwargs": tuple((key, _dump_control_value(item)) for key, item in value.kwargs),
        }
    if isinstance(value, Select):
        return {
            "select": {
                "condition": _dump_control_value(value.condition),
                "then": _dump_control_value(value.then_value),
                "else": _dump_control_value(value.else_value),
            }
        }
    if isinstance(value, SymExpr):
        return dump_prepared_value(value)
    if is_dataclass(value) or isinstance(value, tuple | list | dict):
        return dump_prepared_value(value)
    return value
