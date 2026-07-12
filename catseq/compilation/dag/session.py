"""DAG-native compiler session and its initial multi-pass implementation."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from ...debug import annotate_atomic
from ...expr import Expr
from ...expr.realize import _realize_atomic
from ...morphism.arena import ArenaOperation, ArenaProgram, NodeKind
from ...types.common import (
    AtomicMorphism,
    Channel,
    DebugBreadcrumb,
    OperationType,
    State,
    TIMING_CRITICAL_OPERATIONS,
    TimingKind,
    TimedRegion,
)
from ..pipeline import (
    LogicalEvent,
    _collapse_board_scoped_blackboxes,
    _fuse_zero_gap_ramp_handoffs,
    _translate_board_events,
    analyze_costs_and_epochs,
    generate_final_calls,
    schedule_and_optimize,
    validate_constraints,
)
from ..types import OASMAddress
from .types import CompileDelta, CompileResult


@dataclass(frozen=True, slots=True)
class _BoundaryState:
    initial: State | None
    end: State | None
    effective_start: State | None
    effective_end: State | None
    has_effective: bool


@dataclass(frozen=True, slots=True)
class _DagEvent:
    event_id: int
    source_node_id: int
    timestamp_cycles: int
    operation: ArenaOperation


@dataclass(frozen=True, slots=True)
class _Fragment:
    duration_cycles: int
    states: Mapping[Channel, _BoundaryState]
    operation: ArenaOperation | None = None


def _resolve_duration(value: object, bindings: Mapping[str, object]) -> int:
    resolved = value.resolve(None, bindings) if isinstance(value, Expr) else value
    if not isinstance(resolved, int):
        raise TypeError(f"Duration resolved to {type(resolved).__name__}, expected int")
    if resolved < 0:
        raise ValueError("Duration must be non-negative")
    return resolved


def _atomic_fragment(
    node_id: int,
    operation: ArenaOperation,
    bindings: Mapping[str, object],
) -> _Fragment:
    concrete = _realize_atomic(operation, bindings)
    duration = _resolve_duration(concrete.duration_cycles, bindings)
    channel = concrete.channel
    if channel is None:
        raise ValueError(f"Atomic node {node_id} has no channel")
    has_effective = concrete.operation_type != OperationType.IDENTITY
    state = _BoundaryState(
        initial=concrete.start_state,
        end=concrete.end_state,
        effective_start=concrete.start_state,
        effective_end=concrete.end_state,
        has_effective=has_effective,
    )
    return _Fragment(duration, {channel: state}, concrete)


def _combine_state(
    left: _BoundaryState | None,
    right: _BoundaryState | None,
) -> _BoundaryState | None:
    if left is None:
        return right
    if right is None:
        return left
    return _BoundaryState(
        initial=left.initial,
        end=right.end,
        effective_start=(
            left.effective_start if left.has_effective else right.effective_start
        ),
        effective_end=(
            right.effective_end if right.has_effective else left.effective_end
        ),
        has_effective=left.has_effective or right.has_effective,
    )


def _serial_fragment(
    node_id: int,
    left: _Fragment,
    right: _Fragment,
    *,
    strict: bool,
) -> _Fragment:
    states = {}
    for channel in left.states.keys() | right.states.keys():
        left_state = left.states.get(channel)
        right_state = right.states.get(channel)
        if (
            strict
            and left_state is not None
            and right_state is not None
            and left_state.has_effective
            and right_state.has_effective
            and left_state.effective_end != right_state.effective_start
        ):
            raise ValueError(
                f"State mismatch at arena node {node_id} on {channel.global_id}: "
                f"{left_state.effective_end!r} -> {right_state.effective_start!r}"
            )
        combined = _combine_state(left_state, right_state)
        if combined is not None:
            states[channel] = combined
    return _Fragment(
        left.duration_cycles + right.duration_cycles,
        states,
    )


def _parallel_fragment(left: _Fragment, right: _Fragment) -> _Fragment:
    overlap = left.states.keys() & right.states.keys()
    if overlap:
        channels = sorted(channel.global_id for channel in overlap)
        raise ValueError(f"Parallel state overlap: {channels}")
    return _Fragment(
        max(left.duration_cycles, right.duration_cycles),
        {**left.states, **right.states},
    )


def _evaluate(
    program: ArenaProgram,
    bindings: Mapping[str, object],
    reachable_nodes: frozenset[int],
    cached: Mapping[int, _Fragment] | None = None,
    dirty_nodes: frozenset[int] | None = None,
) -> tuple[_Fragment, dict[int, _Fragment]]:
    fragments = {} if cached is None else dict(cached)
    dirty = (
        frozenset(range(len(program.kinds)))
        if dirty_nodes is None
        else dirty_nodes
    )
    for node_id in sorted(reachable_nodes):
        kind = program.kinds[node_id]
        if node_id not in dirty and node_id in fragments:
            continue
        if kind == NodeKind.ATOMIC:
            operation = program.payload[node_id]
            if not isinstance(operation, (AtomicMorphism, TimedRegion)):
                raise TypeError(f"Atomic node {node_id} has invalid payload")
            fragment = _atomic_fragment(node_id, operation, bindings)
        elif kind == NodeKind.WAIT:
            fragment = _Fragment(
                _resolve_duration(program.payload[node_id], bindings),
                {},
            )
        elif kind in {NodeKind.AUTO_SERIAL, NodeKind.STRICT_SERIAL}:
            left = fragments.get(program.left[node_id])
            right = fragments.get(program.right[node_id])
            if left is None or right is None:
                raise AssertionError("Serial child was not evaluated")
            fragment = _serial_fragment(
                node_id,
                left,
                right,
                strict=kind == NodeKind.STRICT_SERIAL,
            )
        elif kind == NodeKind.PARALLEL:
            left = fragments.get(program.left[node_id])
            right = fragments.get(program.right[node_id])
            if left is None or right is None:
                raise AssertionError("Parallel child was not evaluated")
            fragment = _parallel_fragment(
                left,
                right,
            )
        elif kind == NodeKind.ANNOTATE:
            child = fragments.get(program.left[node_id])
            if child is None:
                raise AssertionError("Annotated child was not evaluated")
            fragment = child
        else:
            raise TypeError(f"Unsupported arena node kind {kind}")
        fragments[node_id] = fragment
    root = fragments.get(program.root)
    if root is None:
        raise AssertionError("Arena root was not evaluated")
    return root, fragments


def _parameter_names(value: object, seen: set[int]) -> set[str]:
    if isinstance(value, Expr):
        result = {str(value.value)} if value.kind == "var" else set()
        for argument in value.args:
            result.update(_parameter_names(argument, seen))
        return result
    value_id = id(value)
    if value_id in seen:
        return set()
    seen.add(value_id)
    if isinstance(value, dict):
        result = set()
        for item in value.values():
            result.update(_parameter_names(item, seen))
        return result
    if isinstance(value, (tuple, list)):
        result = set()
        for item in value:
            result.update(_parameter_names(item, seen))
        return result
    if is_dataclass(value) and not isinstance(value, type):
        result = set()
        for field in fields(value):
            result.update(_parameter_names(getattr(value, field.name), seen))
        return result
    return set()


def _node_dependencies(
    program: ArenaProgram,
    reachable_nodes: frozenset[int],
) -> dict[int, frozenset[str]]:
    result: dict[int, frozenset[str]] = {}
    for node_id in sorted(reachable_nodes):
        payload = program.payload[node_id]
        dependencies = _parameter_names(payload, set())
        left = program.left[node_id]
        right = program.right[node_id]
        if left >= 0:
            dependencies.update(result[left])
        if right >= 0:
            dependencies.update(result[right])
        result[node_id] = frozenset(dependencies)
    return result


def _reachable_nodes(program: ArenaProgram) -> frozenset[int]:
    result = set()
    stack = [program.root]
    while stack:
        node_id = stack.pop()
        if node_id in result:
            continue
        result.add(node_id)
        left = program.left[node_id]
        right = program.right[node_id]
        if left >= 0:
            stack.append(left)
        if right >= 0:
            stack.append(right)
    return frozenset(result)


def _timeline_events(
    program: ArenaProgram,
    fragments: Mapping[int, _Fragment],
) -> tuple[_DagEvent, ...]:
    result: list[_DagEvent] = []
    stack: list[tuple[int, int, tuple[DebugBreadcrumb, ...]]] = [
        (program.root, 0, ())
    ]
    while stack:
        node_id, timestamp, breadcrumbs = stack.pop()
        kind = program.kinds[node_id]
        fragment = fragments.get(node_id)
        if fragment is None:
            raise AssertionError(f"Node {node_id} has no compiled fragment")
        if kind == NodeKind.ATOMIC:
            operation = fragment.operation
            if operation is not None:
                annotated = annotate_atomic(operation, breadcrumbs)
                result.append(
                    _DagEvent(
                        event_id=len(result),
                        source_node_id=node_id,
                        timestamp_cycles=timestamp,
                        operation=annotated,
                    )
                )
            continue
        if kind == NodeKind.WAIT:
            continue
        left = program.left[node_id]
        right = program.right[node_id]
        if kind in {NodeKind.AUTO_SERIAL, NodeKind.STRICT_SERIAL}:
            left_fragment = fragments.get(left)
            if left_fragment is None:
                raise AssertionError(f"Node {left} has no compiled fragment")
            right_breadcrumb = program.payload[node_id]
            right_breadcrumbs = breadcrumbs
            if isinstance(right_breadcrumb, DebugBreadcrumb):
                right_breadcrumbs = (right_breadcrumb,) + breadcrumbs
            stack.append(
                (
                    right,
                    timestamp + left_fragment.duration_cycles,
                    right_breadcrumbs,
                )
            )
            stack.append((left, timestamp, breadcrumbs))
            continue
        if kind == NodeKind.PARALLEL:
            right_breadcrumb = program.payload[node_id]
            right_breadcrumbs = breadcrumbs
            if isinstance(right_breadcrumb, DebugBreadcrumb):
                right_breadcrumbs = (right_breadcrumb,) + breadcrumbs
            stack.append((right, timestamp, right_breadcrumbs))
            stack.append((left, timestamp, breadcrumbs))
            continue
        if kind == NodeKind.ANNOTATE:
            node_breadcrumbs = program.payload[node_id]
            if not isinstance(node_breadcrumbs, tuple):
                raise TypeError(f"Annotate node {node_id} has invalid payload")
            stack.append(
                (
                    program.left[node_id],
                    timestamp,
                    node_breadcrumbs + breadcrumbs,
                )
            )
            continue
        raise TypeError(f"Unsupported arena node kind {kind}")
    return tuple(result)


def _events_by_board(
    program: ArenaProgram,
    fragment: _Fragment,
    fragments: Mapping[int, _Fragment],
) -> tuple[
    dict[OASMAddress, list[LogicalEvent]],
    dict[OASMAddress, frozenset[int]],
]:
    result: dict[OASMAddress, list[LogicalEvent]] = {}
    representative_by_board: dict[OASMAddress, Channel] = {}
    source_nodes_by_board: dict[OASMAddress, set[int]] = {}
    for event in _timeline_events(program, fragments):
        channel = event.operation.channel
        if channel is None:
            raise ValueError(
                f"Atomic arena node {event.source_node_id} has no channel"
            )
        try:
            address = OASMAddress(channel.board.id.lower().replace("_", ""))
        except ValueError:
            address = OASMAddress.RWG0
        representative_by_board.setdefault(address, channel)
        result.setdefault(address, [])
        source_nodes_by_board.setdefault(address, set()).add(event.source_node_id)
        if event.operation.operation_type != OperationType.IDENTITY:
            result[address].append(
                LogicalEvent(
                    timestamp_cycles=event.timestamp_cycles,
                    operation=event.operation,
                    is_critical=(
                        event.operation.operation_type
                        in TIMING_CRITICAL_OPERATIONS
                    ),
                )
            )

    for address, channel in representative_by_board.items():
        boundary = fragment.states[channel]
        horizon = AtomicMorphism(
            channel=channel,
            start_state=boundary.effective_end,
            end_state=boundary.effective_end,
            duration_cycles=0,
            operation_type=OperationType.IDENTITY,
            timing_kind=TimingKind.DELAY,
        )
        result[address].append(
            LogicalEvent(
                timestamp_cycles=fragment.duration_cycles,
                operation=horizon,
                is_critical=True,
            )
        )

    for events in result.values():
        events.sort(
            key=lambda event: (
                event.timestamp_cycles,
                event.operation.channel.global_id
                if event.operation.channel is not None
                else "",
            )
        )
    return result, {
        address: frozenset(source_nodes)
        for address, source_nodes in source_nodes_by_board.items()
    }


def _stable_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if isinstance(value, Enum):
        return (type(value), value.name)
    if callable(value):
        return ("callable", id(value))
    if isinstance(value, tuple):
        return tuple(_stable_value(item) for item in value)
    if isinstance(value, list):
        return tuple(_stable_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(
            sorted((repr(key), _stable_value(item)) for key, item in value.items())
        )
    if is_dataclass(value) and not isinstance(value, type):
        return (
            type(value),
            tuple(
                (field.name, _stable_value(getattr(value, field.name)))
                for field in fields(value)
                if field.name not in {"debug_id", "debug_trace"}
            ),
        )
    return (type(value), repr(value))


def _board_signature(events: list[LogicalEvent]) -> tuple[object, ...]:
    return tuple(
        (event.timestamp_cycles, _stable_value(event.operation))
        for event in events
    )


def _requires_global_recompile(
    events_by_board: Mapping[OASMAddress, list[LogicalEvent]],
) -> bool:
    global_types = {
        OperationType.OPAQUE_OASM_FUNC,
        OperationType.SYNC_MASTER,
        OperationType.SYNC_SLAVE,
    }
    return any(
        event.operation.operation_type in global_types
        for events in events_by_board.values()
        for event in events
    )


class CompilerSession:
    """Stateful cache seam for first and incremental DAG compilation."""

    __slots__ = (
        "_assembler_seq",
        "_bindings",
        "_board_signatures",
        "_dependencies",
        "_fragments",
        "_last_calls",
        "_program",
        "_reachable_nodes",
        "_reverse_parameters",
        "_revision",
        "_verbose",
    )

    def __init__(
        self,
        program: ArenaProgram,
        assembler_seq: object | None = None,
        *,
        verbose: bool = False,
    ) -> None:
        self._program = program
        self._assembler_seq = assembler_seq
        self._verbose = verbose
        self._bindings: dict[str, object] = {}
        self._board_signatures: dict[OASMAddress, tuple[object, ...]] = {}
        self._reachable_nodes = _reachable_nodes(program)
        self._dependencies = _node_dependencies(program, self._reachable_nodes)
        reverse: dict[str, set[int]] = {}
        for node_id in self._reachable_nodes:
            parameters = self._dependencies[node_id]
            for parameter in parameters:
                reverse.setdefault(parameter, set()).add(node_id)
        self._reverse_parameters = {
            parameter: frozenset(nodes) for parameter, nodes in reverse.items()
        }
        self._fragments: dict[int, _Fragment] = {}
        self._last_calls: dict[OASMAddress, tuple] = {}
        self._revision = 0

    def bind(self, bindings: Mapping[str, object]) -> CompileResult:
        next_bindings = {**self._bindings, **bindings}
        required = self._dependencies[self._program.root]
        missing = required - next_bindings.keys()
        if missing:
            raise KeyError(f"Missing bindings: {sorted(missing)}")
        changed_parameters = {
            parameter
            for parameter, value in bindings.items()
            if parameter not in self._bindings or self._bindings[parameter] != value
        }
        if self._revision == 0:
            dirty_nodes = self._reachable_nodes
        else:
            dirty_nodes = frozenset().union(
                *(
                    self._reverse_parameters.get(parameter, frozenset())
                    for parameter in changed_parameters
                )
            )
        if not dirty_nodes:
            self._bindings = next_bindings
            self._revision += 1
            return CompileResult(
                calls_by_board=MappingProxyType(dict(self._last_calls)),
                delta=CompileDelta(
                    revision=self._revision,
                    dirty_nodes=frozenset(),
                    recompiled_boards=frozenset(),
                    changed_boards=frozenset(),
                ),
            )

        fragment, next_fragments = _evaluate(
            self._program,
            next_bindings,
            self._reachable_nodes,
            self._fragments,
            dirty_nodes,
        )
        events_by_board, source_nodes_by_board = _events_by_board(
            self._program,
            fragment,
            next_fragments,
        )
        next_signatures = {
            address: _board_signature(events)
            for address, events in events_by_board.items()
        }
        signature_changes = {
            address
            for address in self._board_signatures.keys() | next_signatures.keys()
            if self._board_signatures.get(address) != next_signatures.get(address)
        }
        recompiled_boards = (
            set(next_signatures)
            if signature_changes and _requires_global_recompile(events_by_board)
            else signature_changes
        )
        dirty_events = {
            address: events_by_board[address]
            for address in recompiled_boards
            if address in events_by_board
        }
        try:
            for address, events in dirty_events.items():
                normalized = _collapse_board_scoped_blackboxes(address, events)
                dirty_events[address] = normalized
                _translate_board_events(address, normalized)
            _fuse_zero_gap_ramp_handoffs(dirty_events)
            if dirty_events:
                analyze_costs_and_epochs(
                    dirty_events,
                    self._assembler_seq,
                    verbose=self._verbose,
                )
                schedule_and_optimize(dirty_events, verbose=self._verbose)
                validate_constraints(dirty_events, verbose=self._verbose)
                generated = generate_final_calls(
                    dirty_events,
                    verbose=self._verbose,
                )
            else:
                generated = {}
        except (TypeError, ValueError) as error:
            source_nodes = sorted(
                {
                    node_id
                    for address in recompiled_boards
                    for node_id in source_nodes_by_board.get(address, ())
                }
            )
            raise type(error)(
                f"{error} (originating arena nodes: {source_nodes})"
            ) from error
        immutable_calls = dict(self._last_calls)
        for address in recompiled_boards:
            if address in generated:
                immutable_calls[address] = tuple(generated[address])
            else:
                immutable_calls.pop(address, None)
        self._revision += 1
        changed_boards = frozenset(
            address
            for address in self._last_calls.keys() | immutable_calls.keys()
            if self._last_calls.get(address) != immutable_calls.get(address)
        )
        self._bindings = next_bindings
        self._board_signatures = next_signatures
        self._fragments = next_fragments
        self._last_calls = immutable_calls
        return CompileResult(
            calls_by_board=MappingProxyType(dict(immutable_calls)),
            delta=CompileDelta(
                revision=self._revision,
                dirty_nodes=dirty_nodes,
                recompiled_boards=frozenset(recompiled_boards),
                changed_boards=changed_boards,
            ),
        )
