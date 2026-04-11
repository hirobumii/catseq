"""
Public morphism API.
"""

from ..lanes import Lane
from .compose import (
    auto_compose_morphisms,
    parallel_compose_morphisms,
    strict_compose_morphisms,
)
from .core import Morphism, from_atomic, identity
from .deferred import MorphismDef

__all__ = [
    "Lane",
    "Morphism",
    "MorphismDef",
    "from_atomic",
    "identity",
    "strict_compose_morphisms",
    "auto_compose_morphisms",
    "parallel_compose_morphisms",
]
