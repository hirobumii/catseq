"""Lower state-dependent template applications into the concrete Morphism DAG."""

from __future__ import annotations

from typing import cast

from ..expr import Expr
from ..types.common import AtomicMorphism, Channel, DebugBreadcrumb, TimedRegion
from .arena import (
    ArenaProgram,
    DeferredApplication,
    DeferredBatch,
    DeferredChannel,
    DeferredRepeat,
    NodeKind,
    ProgramArena,
)
from .compose import (
    auto_compose_morphisms,
    parallel_compose_morphisms,
    strict_compose_morphisms,
)
from .core import Morphism, _arena_scope, from_atomic
from .deferred import (
    MorphismDef,
    _apply_deferred_operations,
    _deferred_lowering_scope,
)
from ..types.rwg import RWGUninitialized


_LOWERED_KINDS = frozenset(
    {
        NodeKind.DEFERRED_APPLY,
        NodeKind.DEFERRED_CHANNEL,
        NodeKind.DEFERRED_BATCH,
        NodeKind.REPEAT,
    }
)


def _reachable_nodes(program: ArenaProgram) -> frozenset[int]:
    reachable: set[int] = set()
    stack = [program.root]
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        left = program.left[node_id]
        right = program.right[node_id]
        if left >= 0:
            stack.append(left)
        if right >= 0:
            stack.append(right)
    return frozenset(reachable)


def materialize_deferred_program(program: ArenaProgram) -> Morphism:
    """Replay one reachable DAG, specializing deferred nodes topologically."""
    reachable = _reachable_nodes(program)
    if not any(program.kinds[node_id] in _LOWERED_KINDS for node_id in reachable):
        raise ValueError("Program has no deferred applications to materialize")

    lowered: dict[int, Morphism] = {}
    with _arena_scope(ProgramArena()), _deferred_lowering_scope():
        for node_id in sorted(reachable):
            kind = program.kinds[node_id]
            if kind == NodeKind.ATOMIC:
                operation = program.payload[node_id]
                if not isinstance(operation, (AtomicMorphism, TimedRegion)):
                    raise TypeError(f"Atomic node {node_id} has invalid payload")
                result = from_atomic(operation)
            elif kind == NodeKind.WAIT:
                duration = program.payload[node_id]
                if not isinstance(duration, (int, Expr)):
                    raise TypeError(f"Wait node {node_id} has invalid payload")
                result = Morphism._from_wait_cycles(duration)
            elif kind in {NodeKind.AUTO_SERIAL, NodeKind.STRICT_SERIAL}:
                left = lowered[program.left[node_id]]
                right = lowered[program.right[node_id]]
                breadcrumb = program.payload[node_id]
                right_breadcrumb = (
                    breadcrumb
                    if isinstance(breadcrumb, DebugBreadcrumb)
                    else None
                )
                if kind == NodeKind.STRICT_SERIAL:
                    result = strict_compose_morphisms(
                        left,
                        right,
                        rhs_breadcrumb=right_breadcrumb,
                    )
                else:
                    result = auto_compose_morphisms(
                        left,
                        right,
                        rhs_breadcrumb=right_breadcrumb,
                    )
            elif kind == NodeKind.PARALLEL:
                breadcrumb = program.payload[node_id]
                result = parallel_compose_morphisms(
                    lowered[program.left[node_id]],
                    lowered[program.right[node_id]],
                    rhs_breadcrumb=(
                        breadcrumb
                        if isinstance(breadcrumb, DebugBreadcrumb)
                        else None
                    ),
                )
            elif kind == NodeKind.ANNOTATE:
                breadcrumbs = program.payload[node_id]
                if not isinstance(breadcrumbs, tuple):
                    raise TypeError(
                        f"Annotate node {node_id} has invalid payload"
                    )
                result = lowered[program.left[node_id]]._annotated(breadcrumbs)
            elif kind == NodeKind.DEFERRED_APPLY:
                application = program.payload[node_id]
                if not isinstance(application, DeferredApplication):
                    raise TypeError(
                        f"Deferred apply node {node_id} has invalid payload"
                    )
                raw_operations = dict(application.channel_operations)
                if not all(
                    isinstance(operation, MorphismDef)
                    for operation in raw_operations.values()
                ):
                    raise TypeError(
                        f"Deferred apply node {node_id} contains an invalid template"
                    )
                operations = cast(
                    dict[Channel, MorphismDef],
                    raw_operations,
                )
                try:
                    result = _apply_deferred_operations(
                        lowered[program.left[node_id]],
                        operations,
                        dict(application.application_breadcrumbs),
                    )
                except (TypeError, ValueError) as error:
                    raise type(error)(
                        f"{error} (deferred apply arena node {node_id})"
                    ) from error
            elif kind == NodeKind.DEFERRED_CHANNEL:
                deferred_channel = program.payload[node_id]
                if not isinstance(deferred_channel, DeferredChannel) or not isinstance(
                    deferred_channel.definition,
                    MorphismDef,
                ):
                    raise TypeError(
                        f"Deferred channel node {node_id} has invalid payload"
                    )
                try:
                    result = deferred_channel.definition._execute_on_channel(
                        deferred_channel.channel,
                        deferred_channel.start_state,
                    )
                except (TypeError, ValueError) as error:
                    raise type(error)(
                        f"{error} (deferred channel arena node {node_id})"
                    ) from error
            elif kind == NodeKind.DEFERRED_BATCH:
                batch = program.payload[node_id]
                if not isinstance(batch, DeferredBatch):
                    raise TypeError(
                        f"Deferred batch node {node_id} has invalid payload"
                    )
                source = lowered[program.left[node_id]]
                result = Morphism._from_wait_cycles(0)
                for channel, definition in batch.channel_operations:
                    if not isinstance(definition, MorphismDef):
                        raise TypeError(
                            f"Deferred batch node {node_id} contains an invalid template"
                        )
                    start_state = (
                        source.effective_end_state(channel) or RWGUninitialized()
                    )
                    channel_result = definition._execute_on_channel(
                        channel,
                        start_state,
                    )
                    result = (
                        channel_result
                        if not result.channels
                        else parallel_compose_morphisms(result, channel_result)
                    )
            elif kind == NodeKind.REPEAT:
                repeat = program.payload[node_id]
                if not isinstance(repeat, DeferredRepeat):
                    raise TypeError(f"Repeat node {node_id} has invalid payload")
                from ..control import _materialize_repeat_morphism

                result = _materialize_repeat_morphism(
                    lowered[program.left[node_id]],
                    repeat.count,
                    repeat.assembler_sequence,
                )
            else:
                raise TypeError(
                    f"Unsupported arena node kind {kind.name} during deferred lowering"
                )
            lowered[node_id] = result
    return lowered[program.root]


def lower_deferred_program(program: ArenaProgram) -> ArenaProgram:
    """Return compiler-ready concrete DAG; preserve already-concrete IDs."""
    reachable = _reachable_nodes(program)
    if not any(program.kinds[node_id] in _LOWERED_KINDS for node_id in reachable):
        return program
    return materialize_deferred_program(program).arena_program
