"""
Runtime Program IR for CatSeq V2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from catseq.morphism import Morphism as LegacyMorphism

from ..expr import resolve_value
from ..morphism import Morphism


@dataclass(frozen=True)
class BitVec:
    bits: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "bits", tuple(1 if bit else 0 for bit in self.bits))

    @classmethod
    def zeros(cls, size: int) -> "BitVec":
        return cls((0,) * size)

    @classmethod
    def from_indices(cls, size: int, indices: tuple[int, ...] | list[int]) -> "BitVec":
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

    def __or__(self, other: "BitVec") -> "BitVec":
        return BitVec(tuple(left | right for left, right in zip(self.bits, other.bits, strict=True)))

    def __and__(self, other: "BitVec") -> "BitVec":
        return BitVec(tuple(left & right for left, right in zip(self.bits, other.bits, strict=True)))

    def __xor__(self, other: "BitVec") -> "BitVec":
        return BitVec(tuple(left ^ right for left, right in zip(self.bits, other.bits, strict=True)))

    def __invert__(self) -> "BitVec":
        return BitVec(tuple(0 if bit else 1 for bit in self.bits))

    def count(self) -> int:
        return sum(self.bits)

    def iter_ones(self):
        for index, bit in enumerate(self.bits):
            if bit:
                yield index

    def with_bit(self, index: int, value: int | bool) -> "BitVec":
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
    def from_rows(cls, rows: list[BitVec] | tuple[BitVec, ...]) -> "BitMatrix":
        return cls(tuple(rows))

    @classmethod
    def from_nested_lists(cls, rows: list[list[int]] | tuple[tuple[int, ...], ...]) -> "BitMatrix":
        return cls(tuple(BitVec(tuple(row)) for row in rows))

    @classmethod
    def from_cols(cls, cols: list[BitVec] | tuple[BitVec, ...]) -> "BitMatrix":
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

    def with_row(self, index: int, row: BitVec) -> "BitMatrix":
        rows = list(self.rows)
        rows[index] = row
        return BitMatrix(tuple(rows))

    @property
    def T(self) -> "BitMatrix":
        return BitMatrix.from_cols(tuple(self.iter_cols()))

    def to_list(self) -> list[list[int]]:
        return [row.to_list() for row in self.rows]


@dataclass(frozen=True)
class Call:
    function: str | Callable[..., object]
    args: tuple[object, ...] = ()
    kwargs: tuple[tuple[str, object], ...] = ()


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
    then_body: "Program | tuple[object, ...]"
    else_body: "Program | tuple[object, ...]" = ()


@dataclass(frozen=True)
class ForRange:
    name: str
    start: object
    stop: object
    body: "Program | tuple[object, ...]"
    step: object = 1


@dataclass(frozen=True)
class While:
    condition: object
    body: "Program | tuple[object, ...]"
    max_iterations: int = 10_000


@dataclass(frozen=True)
class FunctionDef:
    name: str
    params: tuple[str, ...]
    body: "Program | tuple[object, ...]"


@dataclass(frozen=True)
class Return:
    value: object = None


@dataclass(frozen=True)
class ProgramResult:
    morphism: LegacyMorphism
    end_states: dict[object, object]
    env: dict[str, object]


class _ReturnSignal(Exception):
    def __init__(self, value: object):
        self.value = value


class Program:
    __slots__ = ("statements",)

    def __init__(self, *statements: object):
        self.statements = tuple(statements)

    def then(self, *statements: object) -> "Program":
        return Program(*self.statements, *statements)

    def run(
        self,
        *,
        start_states: Mapping[object, object] | object | None = None,
        measurements: Mapping[object, object] | None = None,
        runtime_env: Mapping[str, object] | None = None,
        functions: Mapping[str, Callable[..., object]] | None = None,
    ) -> ProgramResult:
        env = dict(runtime_env or {})
        end_states = dict(start_states or {}) if isinstance(start_states, Mapping) else {}
        if start_states is not None and not isinstance(start_states, Mapping):
            raise ValueError("Program.run requires channel start states as a mapping.")

        state = {
            "legacy": None,
            "end_states": end_states,
            "env": env,
            "measurements": dict(measurements or {}),
            "functions": dict(functions or {}),
            "user_functions": {},
        }
        self._execute_block(self.statements, state)
        legacy = state["legacy"]
        if legacy is None:
            legacy = LegacyMorphism(lanes={}, _duration_cycles=0)
        return ProgramResult(legacy, dict(state["end_states"]), dict(state["env"]))

    def _execute_block(self, statements: tuple[object, ...], state: dict[str, object]) -> None:
        for statement in statements:
            self._execute_statement(statement, state)

    def _execute_statement(self, statement: object, state: dict[str, object]) -> None:
        if isinstance(statement, FunctionDef):
            state["user_functions"][statement.name] = statement
            return
        if isinstance(statement, Measure):
            source = statement.source if statement.source is not None else statement.name
            measurements = state["measurements"]
            if source not in measurements:
                raise KeyError(f"Measurement source {source!r} is not available.")
            state["env"][statement.name] = measurements[source]
            return
        if isinstance(statement, Let | Assign):
            state["env"][statement.name] = self._eval_value(statement.value, state)
            return
        if isinstance(statement, Emit):
            legacy, end_states = statement.morphism.materialize_with_states(
                state["end_states"],
                runtime_env=state["env"],
            )
            current = state["legacy"]
            state["legacy"] = legacy if current is None else current >> legacy
            state["end_states"].update(end_states)
            return
        if isinstance(statement, Branch):
            body = statement.then_body if self._eval_value(statement.condition, state) else statement.else_body
            self._execute_block(self._coerce_block(body), state)
            return
        if isinstance(statement, ForRange):
            start = int(self._eval_value(statement.start, state))
            stop = int(self._eval_value(statement.stop, state))
            step = int(self._eval_value(statement.step, state))
            for value in range(start, stop, step):
                state["env"][statement.name] = value
                self._execute_block(self._coerce_block(statement.body), state)
            return
        if isinstance(statement, While):
            for _ in range(statement.max_iterations):
                if not self._eval_value(statement.condition, state):
                    break
                self._execute_block(self._coerce_block(statement.body), state)
            else:
                raise RuntimeError("While loop exceeded max_iterations.")
            return
        if isinstance(statement, Return):
            raise _ReturnSignal(self._eval_value(statement.value, state))
        if isinstance(statement, Program):
            self._execute_block(statement.statements, state)
            return
        raise TypeError(f"Unsupported program statement: {type(statement)!r}")

    def _eval_value(self, value: object, state: dict[str, object]) -> object:
        if isinstance(value, Call):
            return self._eval_call(value, state)
        return resolve_value(value, None, state["env"])

    def _eval_call(self, call: Call, state: dict[str, object]) -> object:
        args = tuple(self._eval_value(arg, state) for arg in call.args)
        kwargs = {
            key: self._eval_value(val, state)
            for key, val in call.kwargs
        }
        function = call.function
        if isinstance(function, str):
            user_functions = state["user_functions"]
            if function in user_functions:
                return self._invoke_user_function(user_functions[function], args, kwargs, state)
            builtin_functions = state["functions"]
            if function not in builtin_functions:
                raise KeyError(f"Program function {function!r} is not registered.")
            return builtin_functions[function](*args, **kwargs)
        return function(*args, **kwargs)

    def _invoke_user_function(
        self,
        function_def: FunctionDef,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        state: dict[str, object],
    ) -> object:
        if kwargs:
            raise TypeError("Program functions currently support positional arguments only.")
        if len(args) != len(function_def.params):
            raise TypeError(
                f"Function {function_def.name!r} expects {len(function_def.params)} args, got {len(args)}."
            )
        child_state = {
            "legacy": None,
            "end_states": dict(state["end_states"]),
            "env": dict(state["env"]),
            "measurements": state["measurements"],
            "functions": state["functions"],
            "user_functions": state["user_functions"],
        }
        for name, arg in zip(function_def.params, args, strict=True):
            child_state["env"][name] = arg
        try:
            self._execute_block(self._coerce_block(function_def.body), child_state)
        except _ReturnSignal as result:
            return result.value
        return None

    @staticmethod
    def _coerce_block(body: "Program | tuple[object, ...]") -> tuple[object, ...]:
        if isinstance(body, Program):
            return body.statements
        return tuple(body)


Seq = Program
