"""
Helpers for attaching structural provenance to morphism objects.
"""

from __future__ import annotations

import inspect
import linecache
from itertools import count
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING

from .types.common import AtomicMorphism, DebugBreadcrumb, DebugFrame

if TYPE_CHECKING:
    from .compilation.pipeline import LogicalEvent
    from .morphism.core import Morphism
    from .morphism.deferred import MorphismDef
    from .types.common import Channel, OperationType


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_COMPOSE_ID_COUNTER = count(1)


def _display_path(file_path: Path) -> str:
    try:
        return file_path.relative_to(_PROJECT_ROOT).as_posix()
    except ValueError:
        return file_path.as_posix()


def capture_callsite(stacklevel: int = 0) -> DebugFrame | None:
    """
    Capture the source frame `stacklevel` frames above the immediate caller.

    `stacklevel=0` captures the caller of this helper.
    """

    frame = inspect.currentframe()
    target: FrameType | None = frame
    try:
        for _ in range(stacklevel + 1):
            if target is None:
                return None
            target = target.f_back
        if target is None:
            return None
        file_path = Path(target.f_code.co_filename).resolve()
        source_text = linecache.getline(str(file_path), target.f_lineno).strip() or None
        return DebugFrame(
            file_path=_display_path(file_path),
            line_number=target.f_lineno,
            function_name=target.f_code.co_name,
            source_text=source_text,
        )
    finally:
        del frame


def next_compose_id() -> int:
    return next(_COMPOSE_ID_COUNTER)


def factory_breadcrumb(stacklevel: int = 0, note: str | None = None) -> DebugBreadcrumb:
    return DebugBreadcrumb(
        kind="factory",
        frame=capture_callsite(stacklevel + 1),
        note=note,
    )


def deferred_definition_breadcrumb(stacklevel: int = 0) -> DebugBreadcrumb:
    return DebugBreadcrumb(
        kind="deferred_def",
        frame=capture_callsite(stacklevel + 1),
    )


def deferred_apply_breadcrumb(
    definition_frame: DebugFrame | None,
    channel_id: str,
    generator_index: int,
) -> DebugBreadcrumb:
    return DebugBreadcrumb(
        kind="deferred_apply",
        frame=definition_frame,
        channel_id=channel_id,
        generator_index=generator_index,
    )


def compose_breadcrumb(
    compose_kind: str,
    side: str,
    compose_id: int,
    stacklevel: int = 0,
) -> DebugBreadcrumb:
    return DebugBreadcrumb(
        kind="compose",
        frame=capture_callsite(stacklevel + 1),
        compose_kind=compose_kind,
        side=side,
        compose_id=compose_id,
    )


def dict_apply_breadcrumb(
    channel_id: str,
    compose_id: int,
    stacklevel: int = 0,
) -> DebugBreadcrumb:
    return DebugBreadcrumb(
        kind="dict_apply",
        frame=capture_callsite(stacklevel + 1),
        channel_id=channel_id,
        compose_id=compose_id,
    )


def auto_generated_breadcrumb(
    reason: str,
    frame: DebugFrame | None = None,
) -> DebugBreadcrumb:
    return DebugBreadcrumb(
        kind="auto_generated",
        frame=frame,
        reason=reason,
    )


def label_breadcrumb(name: str) -> DebugBreadcrumb:
    return DebugBreadcrumb(kind="label", label=name)


def annotate_atomic(
    atomic: AtomicMorphism,
    breadcrumbs: tuple[DebugBreadcrumb, ...],
) -> AtomicMorphism:
    if not breadcrumbs:
        return atomic
    if not hasattr(type(atomic), "__dataclass_fields__"):
        return atomic
    return atomic.append_debug_breadcrumbs(breadcrumbs)


def annotate_morphism(
    morphism: Morphism,
    breadcrumbs: tuple[DebugBreadcrumb, ...],
) -> Morphism:
    from .lanes import Lane
    from .morphism.core import Morphism

    if not breadcrumbs or not morphism.lanes:
        return morphism

    return Morphism(
        {
            channel: Lane(tuple(annotate_atomic(op, breadcrumbs) for op in lane.operations))
            for channel, lane in morphism.lanes.items()
        }
    )


def _format_frame(frame: DebugFrame | None) -> str:
    if frame is None:
        return "unknown location"
    return frame.describe()


def _format_breadcrumb_lines(
    breadcrumb: DebugBreadcrumb,
    indent: str,
) -> list[str]:
    base = f"{indent}- {breadcrumb.describe()}"
    if breadcrumb.frame is not None:
        base += f" at {_format_frame(breadcrumb.frame)}"
    lines = [base]
    if breadcrumb.note is not None:
        lines.append(f"{indent}  note: {breadcrumb.note}")
    if breadcrumb.frame is not None and breadcrumb.frame.source_text is not None:
        lines.append(f"{indent}  code: {breadcrumb.frame.source_text}")
    return lines


def format_atomic_trace(
    atomic: AtomicMorphism,
    indent: str = "  ",
) -> str:
    lines = [f"{indent}trace:"]
    if not atomic.debug_trace:
        lines.append(f"{indent}  <empty>")
        return "\n".join(lines)
    for breadcrumb in reversed(atomic.debug_trace):
        lines.extend(_format_breadcrumb_lines(breadcrumb, f"{indent}  "))
    return "\n".join(lines)


def format_event_trace(
    event: LogicalEvent,
    indent: str = "  ",
) -> str:
    return format_atomic_trace(event.operation, indent=indent)


def trace_index(
    morphism: Morphism,
    operation_type: OperationType | None = None,
    channel: Channel | None = None,
) -> str:
    lines: list[str] = []
    for morphism_channel, lane in morphism.lanes.items():
        if channel is not None and morphism_channel != channel:
            continue
        for index, op in enumerate(lane.operations):
            if operation_type is not None and op.operation_type != operation_type:
                continue
            lines.append(
                f"{morphism_channel.global_id}[{index}] "
                f"{op.operation_type.name} debug_id={op.debug_id}"
            )
            lines.append(format_atomic_trace(op, indent="    "))
    return "\n".join(lines)


def label(obj: Morphism | MorphismDef, name: str) -> Morphism | MorphismDef:
    from .morphism.core import Morphism
    from .morphism.deferred import MorphismDef

    breadcrumb = label_breadcrumb(name)
    if isinstance(obj, Morphism):
        return annotate_morphism(obj, (breadcrumb,))
    if isinstance(obj, MorphismDef):
        return obj.with_label(name)
    raise TypeError(f"Unsupported debug label target: {type(obj)}")
