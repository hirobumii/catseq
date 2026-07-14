"""PROTOTYPE ONLY: compare flat lanes, object DAGs, and an arena DAG.

Question: can CatSeq retain the structure produced by its existing ``>>`` API in
an integer-indexed arena without recursion, and what are the construction,
traversal, memory, and parameter-rebind costs relative to a flat tuple and a
nested Python-object DAG?

This deliberately models one serial lane.  It is not production CatSeq code and
does not model board scheduling, synchronization, or OASM assembly.
"""

from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass
from functools import partial
import gc
from statistics import median
from time import perf_counter_ns
import tracemalloc


ATOM = 0
SERIAL = 1


@dataclass(frozen=True, slots=True)
class Atom:
    duration: int
    value: int
    value_param: str | None = None
    duration_param: str | None = None

    def bound_duration(self, env: dict[str, int]) -> int:
        return env[self.duration_param] if self.duration_param is not None else self.duration

    def bound_value(self, env: dict[str, int]) -> int:
        return env[self.value_param] if self.value_param is not None else self.value


@dataclass(frozen=True, slots=True)
class FlatSequence:
    operations: tuple[Atom, ...]
    total_duration: int

    @classmethod
    def from_atom(cls, atom: Atom) -> "FlatSequence":
        return cls((atom,), atom.duration)

    def __rshift__(self, atom: Atom) -> "FlatSequence":
        operations = self.operations + (atom,)
        # Match the current Lane behavior: construction rescans the complete
        # operation tuple to derive its summary.
        return FlatSequence(operations, sum(item.duration for item in operations))


@dataclass(frozen=True, slots=True)
class ObjectNode:
    kind: int
    left: "ObjectNode | None"
    right: "ObjectNode | None"
    atom: Atom | None
    total_duration: int


@dataclass(frozen=True, slots=True)
class ObjectSequence:
    root: ObjectNode

    @classmethod
    def from_atom(cls, atom: Atom) -> "ObjectSequence":
        return cls(ObjectNode(ATOM, None, None, atom, atom.duration))

    def __rshift__(self, atom: Atom) -> "ObjectSequence":
        right = ObjectNode(ATOM, None, None, atom, atom.duration)
        root = ObjectNode(
            SERIAL,
            self.root,
            right,
            None,
            self.root.total_duration + atom.duration,
        )
        return ObjectSequence(root)


class Arena:
    """Dense struct-of-arrays DAG storage with child-before-parent NodeIds."""

    __slots__ = ("atoms", "durations", "kinds", "left", "payload", "right")

    def __init__(self) -> None:
        self.kinds = array("b")
        self.left = array("i")
        self.right = array("i")
        self.payload = array("i")
        self.durations = array("q")
        self.atoms: list[Atom] = []

    def add_atom(self, atom: Atom) -> int:
        payload = len(self.atoms)
        self.atoms.append(atom)
        node_id = len(self.kinds)
        self.kinds.append(ATOM)
        self.left.append(-1)
        self.right.append(-1)
        self.payload.append(payload)
        self.durations.append(atom.duration)
        return node_id

    def add_serial(self, left: int, right: int) -> int:
        node_id = len(self.kinds)
        self.kinds.append(SERIAL)
        self.left.append(left)
        self.right.append(right)
        self.payload.append(-1)
        self.durations.append(self.durations[left] + self.durations[right])
        return node_id


@dataclass(frozen=True, slots=True)
class ArenaSequence:
    arena: Arena
    root: int

    @classmethod
    def from_atom(cls, atom: Atom) -> "ArenaSequence":
        arena = Arena()
        return cls(arena, arena.add_atom(atom))

    def __rshift__(self, atom: Atom) -> "ArenaSequence":
        right = self.arena.add_atom(atom)
        return ArenaSequence(self.arena, self.arena.add_serial(self.root, right))

    @property
    def total_duration(self) -> int:
        return self.arena.durations[self.root]


def make_atoms(size: int) -> tuple[Atom, ...]:
    return tuple(Atom(duration=1 + index % 7, value=index) for index in range(size))


def build_flat(atoms: tuple[Atom, ...]) -> FlatSequence:
    sequence = FlatSequence.from_atom(atoms[0])
    for atom in atoms[1:]:
        sequence = sequence >> atom
    return sequence


def build_object(atoms: tuple[Atom, ...]) -> ObjectSequence:
    sequence = ObjectSequence.from_atom(atoms[0])
    for atom in atoms[1:]:
        sequence = sequence >> atom
    return sequence


def build_arena(atoms: tuple[Atom, ...]) -> ArenaSequence:
    sequence = ArenaSequence.from_atom(atoms[0])
    for atom in atoms[1:]:
        sequence = sequence >> atom
    return sequence


def iter_object_atoms(sequence: ObjectSequence):
    stack = [sequence.root]
    while stack:
        node = stack.pop()
        if node.kind == ATOM:
            yield node.atom
        else:
            stack.append(node.right)  # type: ignore[arg-type]
            stack.append(node.left)  # type: ignore[arg-type]


def iter_arena_atoms(sequence: ArenaSequence):
    arena = sequence.arena
    stack = [sequence.root]
    while stack:
        node_id = stack.pop()
        if arena.kinds[node_id] == ATOM:
            yield arena.atoms[arena.payload[node_id]]
        else:
            stack.append(arena.right[node_id])
            stack.append(arena.left[node_id])


def recursive_object_count(node: ObjectNode) -> int:
    if node.kind == ATOM:
        return 1
    return recursive_object_count(node.left) + recursive_object_count(node.right)  # type: ignore[arg-type]


def _mix(value: int, duration: int) -> int:
    result = (value ^ (duration << 7)) & 0xFFFFFFFF
    for _ in range(4):
        result = ((result * 1_664_525 + 1_013_904_223) ^ (result >> 13)) & 0xFFFFFFFF
    return result


def _checksum_atoms(atoms) -> int:
    checksum = 0
    for atom in atoms:
        checksum ^= _mix(atom.value, atom.duration)
    return checksum


def _representation_atoms(
    name: str,
    sequence: FlatSequence | ObjectSequence | ArenaSequence,
):
    if name == "flat_lane":
        if not isinstance(sequence, FlatSequence):
            raise TypeError(name)
        return iter(sequence.operations)
    if name == "object_dag":
        if not isinstance(sequence, ObjectSequence):
            raise TypeError(name)
        return iter_object_atoms(sequence)
    if not isinstance(sequence, ArenaSequence):
        raise TypeError(name)
    return iter_arena_atoms(sequence)


def _representation_duration(
    name: str,
    sequence: FlatSequence | ObjectSequence | ArenaSequence,
) -> int:
    if name == "flat_lane":
        if not isinstance(sequence, FlatSequence):
            raise TypeError(name)
        return sequence.total_duration
    if name == "object_dag":
        if not isinstance(sequence, ObjectSequence):
            raise TypeError(name)
        return sequence.root.total_duration
    if not isinstance(sequence, ArenaSequence):
        raise TypeError(name)
    return sequence.total_duration


def _representation_checksum(
    name: str,
    sequence: FlatSequence | ObjectSequence | ArenaSequence,
) -> int:
    return _checksum_atoms(_representation_atoms(name, sequence))


def _time_ns(operation, repeats: int) -> int:
    samples: list[int] = []
    for _ in range(repeats):
        gc.collect()
        started = perf_counter_ns()
        value = operation()
        elapsed = perf_counter_ns() - started
        if value is None:
            raise AssertionError("benchmark operation returned no value")
        samples.append(elapsed)
        del value
    return int(median(samples))


def _memory_bytes(operation) -> tuple[int, int]:
    gc.collect()
    tracemalloc.start()
    value = operation()
    current, peak = tracemalloc.get_traced_memory()
    if value is None:
        raise AssertionError("memory operation returned no value")
    tracemalloc.stop()
    del value
    gc.collect()
    return current, peak


@dataclass(frozen=True, slots=True)
class RepresentationMeasurement:
    build_ms: float
    traverse_ms: float
    retained_kib: float
    peak_kib: float


def benchmark_representations(
    sizes: tuple[int, ...], repeats: int
) -> dict[str, dict[str, dict[str, float]]]:
    result: dict[str, dict[str, dict[str, float]]] = {}
    builders = {
        "flat_lane": build_flat,
        "object_dag": build_object,
        "arena_dag": build_arena,
    }
    for size in sizes:
        atoms = make_atoms(size)
        expected_duration = sum(atom.duration for atom in atoms)
        size_result: dict[str, dict[str, float]] = {}
        for name, builder in builders.items():
            build_ns = _time_ns(lambda builder=builder: builder(atoms), repeats)
            sequence = builder(atoms)
            actual_duration = _representation_duration(name, sequence)
            if actual_duration != expected_duration:
                raise AssertionError(f"{name} duration mismatch")
            expected_checksum = _checksum_atoms(atoms)
            traverse_ns = _time_ns(
                partial(_representation_checksum, name, sequence), repeats
            )
            if _representation_checksum(name, sequence) != expected_checksum:
                raise AssertionError(f"{name} traversal mismatch")
            del sequence
            current, peak = _memory_bytes(lambda builder=builder: builder(atoms))
            measurement = RepresentationMeasurement(
                build_ms=build_ns / 1_000_000,
                traverse_ms=traverse_ns / 1_000_000,
                retained_kib=current / 1024,
                peak_kib=peak / 1024,
            )
            size_result[name] = asdict(measurement)
        result[str(size)] = size_result
    return result


def benchmark_depth(size: int, repeats: int) -> dict[str, object]:
    atoms = make_atoms(size)
    object_sequence = build_object(atoms)
    arena_sequence = build_arena(atoms)
    recursive_status = "completed"
    try:
        recursive_object_count(object_sequence.root)
    except RecursionError:
        recursive_status = "RecursionError"

    object_ns = _time_ns(
        lambda: sum(1 for _ in iter_object_atoms(object_sequence)), repeats
    )
    arena_ns = _time_ns(
        lambda: sum(1 for _ in iter_arena_atoms(arena_sequence)), repeats
    )
    return {
        "size": size,
        "recursive_object_traversal": recursive_status,
        "iterative_object_count": sum(1 for _ in iter_object_atoms(object_sequence)),
        "iterative_object_ms": object_ns / 1_000_000,
        "iterative_arena_count": sum(1 for _ in iter_arena_atoms(arena_sequence)),
        "iterative_arena_ms": arena_ns / 1_000_000,
    }


@dataclass(slots=True)
class CompiledState:
    calls: list[int]
    timestamps: list[int]
    total_duration: int


def full_compile(atoms: tuple[Atom, ...], env: dict[str, int]) -> CompiledState:
    calls: list[int] = []
    timestamps: list[int] = []
    timestamp = 0
    for atom in atoms:
        duration = atom.bound_duration(env)
        value = atom.bound_value(env)
        timestamps.append(timestamp)
        calls.append(_mix(value, duration))
        timestamp += duration
    return CompiledState(calls, timestamps, timestamp)


class IncrementalPrepared:
    __slots__ = (
        "atoms",
        "duration_users",
        "env",
        "state",
        "value_users",
    )

    def __init__(self, atoms: tuple[Atom, ...], env: dict[str, int]) -> None:
        self.atoms = atoms
        self.env = dict(env)
        self.value_users: dict[str, list[int]] = {}
        self.duration_users: dict[str, list[int]] = {}
        for index, atom in enumerate(atoms):
            if atom.value_param is not None:
                self.value_users.setdefault(atom.value_param, []).append(index)
            if atom.duration_param is not None:
                self.duration_users.setdefault(atom.duration_param, []).append(index)
        self.state = full_compile(atoms, env)

    def bind(self, changes: dict[str, int]) -> tuple[int, int]:
        changed = {
            name for name, value in changes.items() if self.env.get(name) != value
        }
        self.env.update(changes)
        dirty_calls: set[int] = set()
        duration_indexes: list[int] = []
        for name in changed:
            dirty_calls.update(self.value_users.get(name, ()))
            users = self.duration_users.get(name, ())
            dirty_calls.update(users)
            duration_indexes.extend(users)

        for index in dirty_calls:
            atom = self.atoms[index]
            self.state.calls[index] = _mix(
                atom.bound_value(self.env), atom.bound_duration(self.env)
            )

        touched_timestamps = 0
        if duration_indexes:
            first = min(duration_indexes)
            timestamp = self.state.timestamps[first]
            for index in range(first, len(self.atoms)):
                self.state.timestamps[index] = timestamp
                timestamp += self.atoms[index].bound_duration(self.env)
                touched_timestamps += 1
            self.state.total_duration = timestamp
        return len(dirty_calls), touched_timestamps


def make_incremental_atoms(size: int, timing_index: int) -> tuple[Atom, ...]:
    value_stride = max(1, size // 100)
    atoms: list[Atom] = []
    for index in range(size):
        atoms.append(
            Atom(
                duration=3,
                value=index,
                value_param="amp" if index % value_stride == 0 else None,
                duration_param="pulse" if index == timing_index else None,
            )
        )
    return tuple(atoms)


def _benchmark_bind_case(
    atoms: tuple[Atom, ...],
    initial_env: dict[str, int],
    changes: tuple[dict[str, int], ...],
    repeats: int,
) -> dict[str, float | int]:
    full_samples: list[int] = []
    incremental_samples: list[int] = []
    last_touched_calls = 0
    last_touched_timestamps = 0
    final_full: CompiledState | None = None
    final_incremental: CompiledState | None = None

    for _ in range(repeats):
        started = perf_counter_ns()
        env = dict(initial_env)
        for change in changes:
            env.update(change)
            final_full = full_compile(atoms, env)
        full_samples.append(perf_counter_ns() - started)

        prepared = IncrementalPrepared(atoms, initial_env)
        started = perf_counter_ns()
        for change in changes:
            last_touched_calls, last_touched_timestamps = prepared.bind(change)
        incremental_samples.append(perf_counter_ns() - started)
        final_incremental = prepared.state

    if final_full != final_incremental:
        raise AssertionError("incremental bind differs from full compilation")

    full_per_bind = median(full_samples) / len(changes)
    incremental_per_bind = median(incremental_samples) / len(changes)
    return {
        "full_us_per_bind": full_per_bind / 1_000,
        "incremental_us_per_bind": incremental_per_bind / 1_000,
        "speedup": full_per_bind / incremental_per_bind,
        "last_touched_calls": last_touched_calls,
        "last_touched_timestamps": last_touched_timestamps,
    }


def benchmark_incremental(size: int, binds: int, repeats: int) -> dict[str, object]:
    initial = {"amp": 10, "pulse": 7}
    value_changes = tuple({"amp": 11 + index % 2} for index in range(binds))
    timing_changes = tuple({"pulse": 8 + index % 2} for index in range(binds))

    middle_atoms = make_incremental_atoms(size, size // 2)
    tail_atoms = make_incremental_atoms(size, max(0, size - max(1, size // 100)))
    return {
        "size": size,
        "binds": binds,
        "value_only": _benchmark_bind_case(
            middle_atoms, initial, value_changes, repeats
        ),
        "timing_middle": _benchmark_bind_case(
            middle_atoms, initial, timing_changes, repeats
        ),
        "timing_last_1_percent": _benchmark_bind_case(
            tail_atoms, initial, timing_changes, repeats
        ),
    }


def run_all(
    *,
    sizes: tuple[int, ...],
    repeats: int,
    deep_size: int,
    incremental_size: int,
    binds: int,
) -> dict[str, object]:
    return {
        "assumptions": {
            "flat_lane": "tuple concatenation plus full summary rescan",
            "object_dag": "left-deep immutable Python objects, iterative traversal",
            "arena_dag": "dense array arena with integer NodeIds, iterative traversal",
            "incremental": "atom-local lowering plus suffix timestamp invalidation",
        },
        "representations": benchmark_representations(sizes, repeats),
        "depth": benchmark_depth(deep_size, repeats),
        "incremental": benchmark_incremental(
            incremental_size, binds, repeats
        ),
    }
