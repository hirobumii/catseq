"""
Time conversion utilities for CatSeq framework.

Provides conversion between human-readable time units (microseconds) and 
hardware clock cycles for precise timing control.
"""

# RTMQ 硬件时钟频率：250 MHz
CLOCK_FREQ_HZ = 250_000_000
CYCLES_PER_US = CLOCK_FREQ_HZ / 1_000_000  # 250 cycles per microsecond


def us_to_cycles(microseconds: float) -> int:
    """将微秒转换为时钟周期数
    
    Args:
        microseconds: 时间长度（微秒）
        
    Returns:
        对应的时钟周期数
    """
    return int(microseconds * CYCLES_PER_US)


def cycles_to_us(cycles: int) -> float:
    """将时钟周期数转换为微秒
    
    Args:
        cycles: 时钟周期数
        
    Returns:
        对应的时间长度（微秒）
    """
    return cycles / CYCLES_PER_US