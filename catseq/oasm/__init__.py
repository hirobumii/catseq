"""
OASM interface module for CatSeq.

This module provides the interface between CatSeq Morphism objects and
the OASM DSL for hardware control.
"""

from .types import OASMAddress, OASMFunction, OASMCall
from .functions import ttl_config, wait_us, my_wait, trig_slave
from .compiler import compile_to_oasm_calls, execute_oasm_calls

__all__ = [
    'OASMAddress',
    'OASMFunction', 
    'OASMCall',
    'ttl_config',
    'wait_us',
    'my_wait',
    'trig_slave',
    'compile_to_oasm_calls',
    'execute_oasm_calls',
]