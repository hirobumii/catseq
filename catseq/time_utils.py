"""
Time conversion utilities for CatSeq framework.

Uses International System of Units (SI) with seconds as base unit.
Internal conversion to hardware clock cycles (machine units).
Hardware: RTMQ clock at 250 MHz (4ns per cycle, mu = 1 cycle)
"""

# Hardware constants
CLOCK_FREQ_HZ = 250_000_000  # 250 MHz
CYCLE_DURATION_S = 4e-9      # 4ns per cycle in seconds

# International unit constants (SI base: seconds)
s = 1.0           # 1 second (SI base unit)
ms = 1e-3         # 1 millisecond = 0.001 seconds
us = 1e-6         # 1 microsecond = 0.000001 seconds
ns = 1e-9         # 1 nanosecond = 0.000000001 seconds
mu = 4e-9         # 1 machine unit = 4ns = 1 clock cycle

# Legacy constants for backward compatibility
CYCLES_PER_US = CLOCK_FREQ_HZ * us


def us_to_cycles(microseconds: float) -> int:
    """将微秒转换为时钟周期数 (Legacy function)

    Args:
        microseconds: 时间长度（微秒）

    Returns:
        对应的时钟周期数
    """
    return round(microseconds * CYCLES_PER_US)


def cycles_to_us(cycles: int) -> float:
    """将时钟周期数转换为微秒 (Legacy function)

    Args:
        cycles: 时钟周期数

    Returns:
        对应的时间长度（微秒）
    """
    return cycles / CYCLES_PER_US


def time_to_cycles(time_seconds: float) -> int:
    """Convert SI time in seconds to machine units (clock cycles).

    Args:
        time_seconds: Time value in seconds (SI unit)

    Returns:
        Time value in machine units (clock cycles)

    Examples:
        time_to_cycles(1.0)       -> 250_000_000  # 1 second
        time_to_cycles(1e-3)      -> 250_000      # 1 millisecond
        time_to_cycles(1e-6)      -> 250          # 1 microsecond
        time_to_cycles(4e-9)      -> 1            # 1 machine unit
    """
    return round(time_seconds * CLOCK_FREQ_HZ)


def cycles_to_time(cycles: int) -> float:
    """Convert machine units (clock cycles) to SI time in seconds.

    Args:
        cycles: Time value in machine units (clock cycles)

    Returns:
        Time value in seconds (SI unit)

    Examples:
        cycles_to_time(250_000_000) -> 1.0    # 1 second
        cycles_to_time(250_000)     -> 1e-3   # 1 millisecond
        cycles_to_time(250)         -> 1e-6   # 1 microsecond
        cycles_to_time(1)           -> 4e-9   # 1 machine unit
    """
    return cycles * CYCLE_DURATION_S