"""Target-independent time units and explicit clock-aware conversions."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from numbers import Real
from typing import TYPE_CHECKING, TypeAlias

from .morphism.core import compiler_only


if TYPE_CHECKING:
    Duration: TypeAlias = float
else:

    class _DurationSourceType:
        """Exact runtime binding for the compiler-only Duration annotation."""

    Duration = _DurationSourceType
_TimeValue: TypeAlias = Real | Decimal

# Source-language SI units. The Rust frontend converts expressions containing
# these names with the selected target profile's clock.
s: Duration = 1.0
ms: Duration = 1e-3
us: Duration = 1e-6
ns: Duration = 1e-9


def cycles(count: int) -> Duration:
    """Spell an exact signed target Cycle Delta in restricted CatSeq source."""

    del count
    compiler_only("catseq.time_utils.cycles")


def us_to_cycles(microseconds: _TimeValue, *, clock_hz: int) -> int:
    """Convert microseconds to an exact Cycle Delta for ``clock_hz``."""

    return _seconds_to_cycles(_decimal(microseconds) / 1_000_000, clock_hz)


def cycles_to_us(cycle_count: int, *, clock_hz: int) -> float:
    """Convert a signed Cycle Delta to microseconds for ``clock_hz``."""

    return cycles_to_time(cycle_count, clock_hz=clock_hz) * 1_000_000


def time_to_cycles(time_seconds: _TimeValue, *, clock_hz: int) -> int:
    """Convert seconds to an exact Cycle Delta for ``clock_hz``."""

    return _seconds_to_cycles(_decimal(time_seconds), clock_hz)


def cycles_to_time(cycle_count: int, *, clock_hz: int) -> float:
    """Convert a signed Cycle Delta to seconds for ``clock_hz``."""

    clock = _clock_hz(clock_hz)
    if isinstance(cycle_count, bool) or not isinstance(cycle_count, int):
        raise TypeError("cycle_count must be an integer")
    return float(Decimal(cycle_count) / Decimal(clock))


def _seconds_to_cycles(seconds: Decimal, clock_hz: int) -> int:
    clock = _clock_hz(clock_hz)
    if not seconds.is_finite():
        raise ValueError("duration must be finite")
    cycle_count = seconds * clock
    integral = cycle_count.to_integral_value()
    if cycle_count != integral:
        raise ValueError(
            f"duration produces non-integral target Cycle Delta {cycle_count}"
        )
    return int(integral)


def _clock_hz(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("clock_hz must be an integer")
    if value <= 0:
        raise ValueError("clock_hz must be greater than zero")
    return value


def _decimal(value: _TimeValue) -> Decimal:
    if isinstance(value, bool):
        raise TypeError("duration must be a real number")
    try:
        if isinstance(value, Decimal):
            return value
        if isinstance(value, Real):
            return Decimal(str(value))
        raise TypeError("duration must be a real number")
    except (InvalidOperation, ValueError) as error:
        raise ValueError("duration must be finite") from error


__all__ = [
    "Duration",
    "cycles",
    "cycles_to_time",
    "cycles_to_us",
    "ms",
    "ns",
    "s",
    "time_to_cycles",
    "us",
    "us_to_cycles",
]
