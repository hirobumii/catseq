"""
OASM interface module for CatSeq.

This module provides the interface between CatSeq Morphism objects and
the OASM DSL for hardware control.
"""

from .types import OASMAddress, OASMFunction, OASMCall
from .functions import ttl_config, ttl_set, wait_us, wait_master, trig_slave
from .compiler import compile_to_oasm_calls, execute_oasm_calls
from .mask_utils import binary_to_rtmq_mask, rtmq_mask_to_binary, encode_rtmq_mask

__all__ = [
    'OASMAddress',
    'OASMFunction', 
    'OASMCall',
    'ttl_config',
    'ttl_set',
    'wait_us',
    'wait_master',
    'trig_slave',
    'compile_to_oasm_calls',
    'execute_oasm_calls',
    'binary_to_rtmq_mask',
    'rtmq_mask_to_binary', 
    'encode_rtmq_mask',
]