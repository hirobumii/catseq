"""
TTL helpers for CatSeq V2.
"""

from __future__ import annotations

from catseq.types.common import OperationType
from catseq.types.ttl import TTLState

from .common import wait
from .morphism import Morphism


def initialize() -> Morphism:
    return Morphism.atomic(
        OperationType.TTL_INIT,
        end_state=TTLState.OFF,
    )


def on() -> Morphism:
    return Morphism.atomic(
        OperationType.TTL_ON,
        state_requirement=TTLState,
        end_state=TTLState.ON,
    )


def off() -> Morphism:
    return Morphism.atomic(
        OperationType.TTL_OFF,
        state_requirement=TTLState,
        end_state=TTLState.OFF,
    )


def pulse(duration: float) -> Morphism:
    return on() >> wait(duration) >> off()


set_high = on
set_low = off
