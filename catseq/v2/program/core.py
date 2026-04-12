"""
Runtime Program IR for CatSeq V2.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from ..expr import resolve_value
from ..morphism import Morphism, RealizedMorphism


@dataclass(frozen=True)
class BitVec:
    bits: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bits", tuple(1 if bit else 0 for bit in self.bits))

    @classmethod
    def zeros(cls, size: int) -> BitVec:
        return cls((0,) * size)

    @classmethod
    def from_indices(cls, size: int, indices: tuple[int, ...] | list[int]) -> BitVec:
        bits = [0] * size
        for index in indices:
            bits[index] = 1
        return cls(tuple(bits))

    def __len__(self) -> int:
        return len(self.bits)

    def __iter__(self):
        return iter(self.bits)

    def __getitem__(self, index: int) -> int:
        return self.bits[index]

    def __bool__(self) -> bool:
        return any(self.bits)

    def __or__(self, other: BitVec) -> BitVec:
        return BitVec(tuple(left | right for left, right in zip(self.bits, other.bits, strict=True)))

    def __and__(self, other: BitVec) -> BitVec:
        return BitVec(tuple(left & right for left, right in zip(self.bits, other.bits, strict=True)))

    def __xor__(self, other: BitVec) -> BitVec:
        return BitVec(tuple(left ^ right for left, right in zip(self.bits, other.bits, strict=True)))

    def __invert__(self) -> BitVec:
        return BitVec(tuple(0 if bit else 1 for bit in self.bits))

    def count(self) -> int:
        return sum(self.bits)

    def iter_ones(self):
        for index, bit in enumerate(self.bits):
            if bit:
                yield index

    def with_bit(self, index: int, value: int | bool) -> BitVec:
        bits = list(self.bits)
        bits[index] = 1 if value else 0
        return BitVec(tuple(bits))

    def to_list(self) -> list[int]:
        return list(self.bits)


@dataclass(frozen=True)
class BitMatrix:
    rows: tuple[BitVec, ...]

    def __post_init__(self) -> None:
        if not self.rows:
            raise ValueError("BitMatrix requires at least one row.")
        width = len(self.rows[0])
        if any(len(row) != width for row in self.rows):
            raise ValueError("All BitMatrix rows must have the same width.")

    @classmethod
    def from_rows(cls, rows: list[BitVec] | tuple[BitVec, ...]) -> BitMatrix:
        return cls(tuple(rows))

    @classmethod
    def from_nested_lists(cls, rows: list[list[int]] | tuple[tuple[int, ...], ...]) -> BitMatrix:
        return cls(tuple(BitVec(tuple(row)) for row in rows))

    @classmethod
    def from_cols(cls, cols: list[BitVec] | tuple[BitVec, ...]) -> BitMatrix:
        if not cols:
            raise ValueError("BitMatrix requires at least one column.")
        nr = len(cols[0])
        rows = []
        for row_index in range(nr):
            rows.append(BitVec(tuple(col[row_index] for col in cols)))
        return cls(tuple(rows))

    @property
    def nr(self) -> int:
        return len(self.rows)

    @property
    def nc(self) -> int:
        return len(self.rows[0])

    def __getitem__(self, index: int) -> BitVec:
        return self.rows[index]

    def iter_rows(self):
        return iter(self.rows)

    def iter_cols(self):
        for col_index in range(self.nc):
            yield BitVec(tuple(row[col_index] for row in self.rows))

    def row(self, index: int) -> BitVec:
        return self.rows[index]

    def col(self, index: int) -> BitVec:
        return BitVec(tuple(row[index] for row in self.rows))

    def with_row(self, index: int, row: BitVec) -> BitMatrix:
        rows = list(self.rows)
        rows[index] = row
        return BitMatrix(tuple(rows))

    @property
    def T(self) -> BitMatrix:
        return BitMatrix.from_cols(tuple(self.iter_cols()))

    def to_list(self) -> list[list[int]]:
        return [row.to_list() for row in self.rows]


@dataclass(frozen=True)
class Call:
    function: str | Callable[..., object]
    args: tuple[object, ...] = ()
    kwargs: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class Select:
    condition: object
    then_value: object
    else_value: object


@dataclass(frozen=True)
class Emit:
    morphism: Morphism


@dataclass(frozen=True)
class Measure:
    name: str
    source: object | None = None


@dataclass(frozen=True)
class Let:
    name: str
    value: object


@dataclass(frozen=True)
class Assign:
    name: str
    value: object


@dataclass(frozen=True)
class Branch:
    condition: object
    then_body: Program | tuple[object, ...]
    else_body: Program | tuple[object, ...] = ()


@dataclass(frozen=True)
class ForRange:
    name: str
    start: object
    stop: object
    body: Program | tuple[object, ...]
    step: object = 1


@dataclass(frozen=True)
class While:
    condition: object
    body: Program | tuple[object, ...]
    max_iterations: int = 10_000


@dataclass(frozen=True)
class FunctionDef:
    name: str
    params: tuple[str, ...]
    body: Program | tuple[object, ...]


@dataclass(frozen=True)
class Return:
    value: object = None


@dataclass(frozen=True)
class ProgramNode:
    kind: str
    children: tuple[int, ...] = ()
    name: str | None = None
    value: object = None
    source: object | None = None
    morphism: Morphism | None = None
    params: tuple[str, ...] = ()
    body_root: int | None = None
    then_root: int | None = None
    else_root: int | None = None
    start: object = None
    stop: object = None
    step: object = 1
    max_iterations: int = 10_000


class ProgramArena:
    def __init__(self) -> None:
        self.nodes: dict[int, ProgramNode] = {}
        self.next_id = 1

    def add(self, node: ProgramNode) -> int:
        node_id = self.next_id
        self.next_id += 1
        self.nodes[node_id] = node
        return node_id


@dataclass(frozen=True)
class ProgramTrace:
    emitted: tuple[RealizedMorphism, ...]
    end_states: dict[object, object]
    env: dict[str, object]

    def combined_emission(self) -> RealizedMorphism:
        realized = RealizedMorphism.empty()
        for morphism in self.emitted:
            realized = realized >> morphism
        return realized


ProgramResult = ProgramTrace


class _ReturnSignal(Exception):
    def __init__(self, value: object):
        self.value = value


class Program:
    __slots__ = ("_arena", "_root_id")

    def __init__(self, *statements: object):
        arena = ProgramArena()
        root_id = self._add_block(arena, statements)
        self._arena = arena
        self._root_id = root_id

    @classmethod
    def _from_arena(cls, arena: ProgramArena, root_id: int) -> Program:
        program = cls.__new__(cls)
        program._arena = arena
        program._root_id = root_id
        return program

    def then(self, *statements: object) -> Program:
        arena = ProgramArena()
        current_root = self._copy_into(arena, self._arena, self._root_id)[self._root_id]
        current_node = arena.nodes[current_root]
        children = list(current_node.children) if current_node.kind == "seq" else [current_root]
        for statement in statements:
            child_root = self._add_statement(arena, statement)
            child_node = arena.nodes[child_root]
            if child_node.kind == "seq":
                children.extend(child_node.children)
            else:
                children.append(child_root)
        root_id = arena.add(ProgramNode("seq", children=tuple(children)))
        return Program._from_arena(arena, root_id)

    def arena_dump(self) -> dict[str, object]:
        dumped_nodes: dict[int, dict[str, object]] = {}
        for node_id, node in sorted(self._arena.nodes.items()):
            dumped: dict[str, object] = {"kind": node.kind}
            if node.children:
                dumped["children"] = node.children
            if node.name is not None:
                dumped["name"] = node.name
            if node.source is not None:
                dumped["source"] = self._dump_value(node.source)
            if node.value is not None:
                dumped["value"] = self._dump_value(node.value)
            if node.morphism is not None:
                dumped["morphism"] = {
                    "root": node.morphism._root_id,
                    "duration_cycles": node.morphism.total_duration_cycles,
                }
            if node.params:
                dumped["params"] = node.params
            if node.body_root is not None:
                dumped["body_root"] = node.body_root
            if node.then_root is not None:
                dumped["then_root"] = node.then_root
            if node.else_root is not None:
                dumped["else_root"] = node.else_root
            if node.start is not None:
                dumped["start"] = self._dump_value(node.start)
            if node.stop is not None:
                dumped["stop"] = self._dump_value(node.stop)
            if node.step != 1:
                dumped["step"] = self._dump_value(node.step)
            if node.max_iterations != 10_000:
                dumped["max_iterations"] = node.max_iterations
            dumped_nodes[node_id] = dumped
        return {"root": self._root_id, "nodes": dumped_nodes}

    def interpret(
        self,
        *,
        start_states: Mapping[object, object] | None = None,
        measurements: Mapping[object, object] | None = None,
        runtime_env: Mapping[str, object] | None = None,
        functions: Mapping[str, Callable[..., object]] | None = None,
    ) -> ProgramTrace:
        env = dict(runtime_env or {})
        end_states = dict(start_states or {})
        state = {
            "emitted": [],
            "end_states": end_states,
            "env": env,
            "measurements": dict(measurements or {}),
            "functions": dict(functions or {}),
            "user_functions": {},
        }
        self._execute_node(self._root_id, state)
        return ProgramTrace(
            emitted=tuple(state["emitted"]),
            end_states=dict(state["end_states"]),
            env=dict(state["env"]),
        )

    def run(
        self,
        *,
        start_states: Mapping[object, object] | None = None,
        measurements: Mapping[object, object] | None = None,
        runtime_env: Mapping[str, object] | None = None,
        functions: Mapping[str, Callable[..., object]] | None = None,
    ) -> ProgramTrace:
        return self.interpret(
            start_states=start_states,
            measurements=measurements,
            runtime_env=runtime_env,
            functions=functions,
        )

    def _execute_node(self, node_id: int, state: dict[str, object]) -> None:
        node = self._arena.nodes[node_id]
        if node.kind == "seq":
            for child in node.children:
                self._execute_node(child, state)
            return
        if node.kind == "function":
            user_functions = state["user_functions"]
            assert isinstance(user_functions, dict)
            user_functions[node.name] = node_id
            return
        if node.kind == "measure":
            source = node.source if node.source is not None else node.name
            measurements = state["measurements"]
            assert isinstance(measurements, dict)
            if source not in measurements:
                raise KeyError(f"Measurement source {source!r} is not available.")
            env = state["env"]
            assert isinstance(env, dict)
            env[node.name] = measurements[source]
            return
        if node.kind in {"let", "assign"}:
            env = state["env"]
            assert isinstance(env, dict)
            env[node.name] = self._eval_value(node.value, state)
            return
        if node.kind == "emit":
            assert node.morphism is not None
            end_states = state["end_states"]
            env = state["env"]
            assert isinstance(end_states, dict)
            assert isinstance(env, dict)
            result = node.morphism._materialize_with_env(end_states, env)
            emitted = state["emitted"]
            assert isinstance(emitted, list)
            emitted.append(result.morphism)
            end_states.update(result.end_states)
            return
        if node.kind == "branch":
            branch_root = node.then_root if self._eval_value(node.value, state) else node.else_root
            if branch_root is not None:
                self._execute_node(branch_root, state)
            return
        if node.kind == "for_range":
            assert node.body_root is not None
            env = state["env"]
            assert isinstance(env, dict)
            start = int(self._eval_value(node.start, state))
            stop = int(self._eval_value(node.stop, state))
            step = int(self._eval_value(node.step, state))
            for value in range(start, stop, step):
                env[node.name] = value
                self._execute_node(node.body_root, state)
            return
        if node.kind == "while":
            assert node.body_root is not None
            for _ in range(node.max_iterations):
                if not self._eval_value(node.value, state):
                    break
                self._execute_node(node.body_root, state)
            else:
                raise RuntimeError("While loop exceeded max_iterations.")
            return
        if node.kind == "return":
            raise _ReturnSignal(self._eval_value(node.value, state))
        raise TypeError(f"Unsupported program node kind: {node.kind!r}")

    def _eval_value(self, value: object, state: dict[str, object]) -> object:
        if isinstance(value, Call):
            return self._eval_call(value, state)
        if isinstance(value, Select):
            selected = value.then_value if self._eval_value(value.condition, state) else value.else_value
            return self._eval_value(selected, state)
        env = state["env"]
        assert isinstance(env, dict)
        return resolve_value(value, None, env)

    def _eval_call(self, call: Call, state: dict[str, object]) -> object:
        args = tuple(self._eval_value(arg, state) for arg in call.args)
        kwargs = {key: self._eval_value(value, state) for key, value in call.kwargs}
        function = call.function
        if isinstance(function, str):
            user_functions = state["user_functions"]
            assert isinstance(user_functions, dict)
            if function in user_functions:
                return self._invoke_user_function(user_functions[function], args, kwargs, state)
            builtin_functions = state["functions"]
            assert isinstance(builtin_functions, dict)
            if function not in builtin_functions:
                raise KeyError(f"Program function {function!r} is not registered.")
            return builtin_functions[function](*args, **kwargs)
        return function(*args, **kwargs)

    def _invoke_user_function(
        self,
        function_node_id: int,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        state: dict[str, object],
    ) -> object:
        function_node = self._arena.nodes[function_node_id]
        if kwargs:
            raise TypeError("Program functions currently support positional arguments only.")
        if len(args) != len(function_node.params):
            raise TypeError(
                f"Function {function_node.name!r} expects {len(function_node.params)} args, got {len(args)}."
            )
        child_state = {
            "emitted": [],
            "end_states": dict(state["end_states"]),
            "env": dict(state["env"]),
            "measurements": state["measurements"],
            "functions": state["functions"],
            "user_functions": state["user_functions"],
        }
        child_env = child_state["env"]
        assert isinstance(child_env, dict)
        for name, arg in zip(function_node.params, args, strict=True):
            child_env[name] = arg
        try:
            assert function_node.body_root is not None
            self._execute_node(function_node.body_root, child_state)
        except _ReturnSignal as result:
            return result.value
        return None

    @classmethod
    def _add_block(cls, arena: ProgramArena, body: Program | Iterable[object]) -> int:
        if isinstance(body, Program):
            return cls._copy_into(arena, body._arena, body._root_id)[body._root_id]
        child_ids: list[int] = []
        for statement in body:
            child_root = cls._add_statement(arena, statement)
            child_node = arena.nodes[child_root]
            if child_node.kind == "seq":
                child_ids.extend(child_node.children)
            else:
                child_ids.append(child_root)
        return arena.add(ProgramNode("seq", children=tuple(child_ids)))

    @classmethod
    def _add_statement(cls, arena: ProgramArena, statement: object) -> int:
        if isinstance(statement, Program):
            return cls._copy_into(arena, statement._arena, statement._root_id)[statement._root_id]
        if isinstance(statement, FunctionDef):
            return arena.add(
                ProgramNode(
                    "function",
                    name=statement.name,
                    params=statement.params,
                    body_root=cls._add_block(arena, statement.body),
                )
            )
        if isinstance(statement, Measure):
            return arena.add(ProgramNode("measure", name=statement.name, source=statement.source))
        if isinstance(statement, Let):
            return arena.add(ProgramNode("let", name=statement.name, value=statement.value))
        if isinstance(statement, Assign):
            return arena.add(ProgramNode("assign", name=statement.name, value=statement.value))
        if isinstance(statement, Emit):
            return arena.add(ProgramNode("emit", morphism=statement.morphism))
        if isinstance(statement, Branch):
            return arena.add(
                ProgramNode(
                    "branch",
                    value=statement.condition,
                    then_root=cls._add_block(arena, statement.then_body),
                    else_root=cls._add_block(arena, statement.else_body),
                )
            )
        if isinstance(statement, ForRange):
            return arena.add(
                ProgramNode(
                    "for_range",
                    name=statement.name,
                    start=statement.start,
                    stop=statement.stop,
                    step=statement.step,
                    body_root=cls._add_block(arena, statement.body),
                )
            )
        if isinstance(statement, While):
            return arena.add(
                ProgramNode(
                    "while",
                    value=statement.condition,
                    body_root=cls._add_block(arena, statement.body),
                    max_iterations=statement.max_iterations,
                )
            )
        if isinstance(statement, Return):
            return arena.add(ProgramNode("return", value=statement.value))
        raise TypeError(f"Unsupported program statement: {type(statement)!r}")

    @staticmethod
    def _copy_into(target: ProgramArena, source: ProgramArena, root_id: int) -> dict[int, int]:
        mapping: dict[int, int] = {}
        stack = [root_id]
        order: list[int] = []
        while stack:
            node_id = stack.pop()
            if node_id in mapping:
                continue
            mapping[node_id] = -1
            node = source.nodes[node_id]
            child_ids = list(node.children)
            if node.body_root is not None:
                child_ids.append(node.body_root)
            if node.then_root is not None:
                child_ids.append(node.then_root)
            if node.else_root is not None:
                child_ids.append(node.else_root)
            stack.extend(child_ids)
            order.append(node_id)
        for old_id in reversed(order):
            node = source.nodes[old_id]
            mapping[old_id] = target.add(
                ProgramNode(
                    kind=node.kind,
                    children=tuple(mapping[child] for child in node.children),
                    name=node.name,
                    value=node.value,
                    source=node.source,
                    morphism=node.morphism,
                    params=node.params,
                    body_root=None if node.body_root is None else mapping[node.body_root],
                    then_root=None if node.then_root is None else mapping[node.then_root],
                    else_root=None if node.else_root is None else mapping[node.else_root],
                    start=node.start,
                    stop=node.stop,
                    step=node.step,
                    max_iterations=node.max_iterations,
                )
            )
        return mapping

    @classmethod
    def _dump_value(cls, value: object) -> object:
        if isinstance(value, Call):
            return {
                "call": value.function if isinstance(value.function, str) else repr(value.function),
                "args": tuple(cls._dump_value(arg) for arg in value.args),
                "kwargs": tuple((key, cls._dump_value(val)) for key, val in value.kwargs),
            }
        if isinstance(value, Select):
            return {
                "select": {
                    "condition": cls._dump_value(value.condition),
                    "then": cls._dump_value(value.then_value),
                    "else": cls._dump_value(value.else_value),
                }
            }
        if isinstance(value, BitVec):
            return {"bitvec": value.to_list()}
        if isinstance(value, BitMatrix):
            return {"bitmatrix": value.to_list()}
        if isinstance(value, tuple):
            return tuple(cls._dump_value(item) for item in value)
        if isinstance(value, list):
            return [cls._dump_value(item) for item in value]
        if isinstance(value, dict):
            return {key: cls._dump_value(item) for key, item in value.items()}
        return repr(value)


Seq = Program
