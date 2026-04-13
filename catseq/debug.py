"""
Helpers for attaching human-readable source provenance to morphism objects.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import FrameType

from .types.common import DebugOrigin


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def capture_callsite(stacklevel: int = 0, note: str | None = None) -> DebugOrigin | None:
    """
    Capture the source location `stacklevel` frames above the immediate caller.

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
        try:
            display_path = file_path.relative_to(_PROJECT_ROOT).as_posix()
        except ValueError:
            display_path = file_path.as_posix()
        return DebugOrigin(
            file_path=display_path,
            line_number=target.f_lineno,
            function_name=target.f_code.co_name,
            note=note,
        )
    finally:
        del frame
