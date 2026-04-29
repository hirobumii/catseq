""" RSP (Signal Processor) abstraction layer. 
This module mirrors the RWG interface style but focuses on Digital Signal Processing operations.
It defines MorphismDefs for PID control, Mixing, Matrix operations, and Lookup Table (LUT) processing.
"""

from typing import List, Optional, Dict, Any
from catseq.morphism import Morphism, MorphismDef, from_atomic


def initialize() -> MorphismDef:
    ...

def set_carrier() -> MorphismDef:
    ...

def pid_config(
    ai_channel: int,
    ao_channel: int,
    setpoint: float,
    kp: float,
    ki: float,
    kd: float = 0.0,
    output_min: float | None = None,
    output_max: float | None = None,
    sample_rate: float | None = None,
) -> MorphismDef:
    ...

def pid_start() -> MorphismDef:
    ...

def pid_hold() -> MorphismDef:
    ...

def pid_release() -> MorphismDef:
    ...