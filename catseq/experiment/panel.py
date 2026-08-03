"""Transport-independent panel updates and publication contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Literal, Protocol
from uuid import uuid4


PanelKind = Literal["plotly", "table", "markdown"]
_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class PanelUpdate:
    """One complete panel snapshot produced by an analyzer."""

    name: str
    data: Any
    analyzer: str | None = None
    title: str | None = None
    kind: PanelKind = "plotly"
    options: dict[str, Any] | None = None
    style: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("panel name must not be empty")
        if self.kind not in {"plotly", "table", "markdown"}:
            raise ValueError(f"unsupported panel kind: {self.kind!r}")


class PanelPublisher(Protocol):
    """Publisher supplied to BaseExp by a runner or local caller."""

    run_id: str

    def start(self) -> None: ...

    def publish(self, update: PanelUpdate) -> str: ...

    def finish(self) -> None: ...

    def close(self) -> None: ...


class NullPanelPublisher:
    """No-op publisher for experiments launched without a panel transport."""

    def __init__(self, *, run_id: str) -> None:
        self.run_id = safe_panel_segment(run_id, fallback="experiment")

    def start(self) -> None:
        pass

    def publish(self, update: PanelUpdate) -> str:
        del update
        return ""

    def finish(self) -> None:
        pass

    def close(self) -> None:
        pass


def safe_panel_segment(value: str, *, fallback: str) -> str:
    result = _SAFE_SEGMENT.sub("_", str(value).strip()).strip("_")
    return result or fallback


def local_run_id(experiment_class: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return safe_panel_segment(
        f"{timestamp}-{experiment_class}-{uuid4().hex[:6]}", fallback="experiment"
    )


__all__ = [
    "NullPanelPublisher",
    "PanelKind",
    "PanelPublisher",
    "PanelUpdate",
    "local_run_id",
    "safe_panel_segment",
]
