"""
Common V2 helpers.
"""

from __future__ import annotations

from .core import Morphism


def wait(duration: float) -> Morphism:
    return Morphism.wait(duration)


def hold(duration: float) -> Morphism:
    return wait(duration)
