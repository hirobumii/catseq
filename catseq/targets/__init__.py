"""Versioned target profiles shipped with CatSeq."""

from __future__ import annotations

from importlib.resources import files
import tomllib
from typing import Any


def rtmq_v2_profile() -> dict[str, Any]:
    """Load the immutable RTMQ2 target selected by CatSeq 0.3."""

    resource = files(__package__).joinpath("rtmq_v2.toml")
    return tomllib.loads(resource.read_text(encoding="utf-8"))
