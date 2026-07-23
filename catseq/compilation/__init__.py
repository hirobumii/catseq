"""Native source compilation and the Python OASM host adapter."""

from .types import OASMAddress, OASMFunction, OASMCall
from .functions import ttl_config, ttl_set, wait_us, wait_master, trig_slave
from .execution import assemble_oasm_calls, oasm_call_plan_to_calls
from .native import CatSeqCompileError, OASMCompileResult, compile_entry
from .mask_utils import binary_to_rtmq_mask, rtmq_mask_to_binary, encode_rtmq_mask
from .runtime import (
    AssembledOASMBoard,
    AssembledOASMProgram,
    BoardEndpoint,
    CatSeqRuntimeError,
    LinuxRawEthernetRuntimeConfig,
    OASMRuntimeFailure,
    OASMRuntimeSuccess,
    execute_oasm_program,
)

__all__ = [
    'OASMAddress',
    'OASMFunction', 
    'OASMCall',
    'ttl_config',
    'ttl_set',
    'wait_us',
    'wait_master',
    'trig_slave',
    'assemble_oasm_calls',
    'oasm_call_plan_to_calls',
    'AssembledOASMBoard',
    'AssembledOASMProgram',
    'BoardEndpoint',
    'CatSeqRuntimeError',
    'LinuxRawEthernetRuntimeConfig',
    'OASMRuntimeFailure',
    'OASMRuntimeSuccess',
    'execute_oasm_program',
    'CatSeqCompileError',
    'OASMCompileResult',
    'compile_entry',
    'binary_to_rtmq_mask',
    'rtmq_mask_to_binary', 
    'encode_rtmq_mask',
]
