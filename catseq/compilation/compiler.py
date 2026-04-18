"""
Compiler orchestration for Morphism -> OASM call translation.
"""

from typing import Dict, List, Union

from ..expr import contains_expr
from . import execution
from .pipeline import (
    LogicalEvent,
    analyze_costs_and_epochs,
    extract_and_translate,
    generate_final_calls,
    schedule_and_optimize,
    validate_constraints,
)
from .types import OASMAddress, OASMCall

OASM_AVAILABLE = execution.OASM_AVAILABLE


def compile_to_oasm_calls(
    morphism,
    assembler_seq=None,
    _return_internal_events: bool = False,
    verbose: bool = False,
) -> Union[Dict[OASMAddress, List[OASMCall]], Dict[OASMAddress, List[LogicalEvent]]]:
    """Compile a morphism into scheduled OASM calls."""
    if contains_expr(morphism):
        raise TypeError(
            "compile_to_oasm_calls requires a fully concrete morphism. "
            "Resolve symbolic expressions first with realize_morphism(...)."
        )
    events_by_board = extract_and_translate(morphism, verbose=verbose)
    analyze_costs_and_epochs(events_by_board, assembler_seq, verbose=verbose)
    schedule_and_optimize(events_by_board, verbose=verbose)
    validate_constraints(events_by_board, verbose=verbose)

    if _return_internal_events:
        return events_by_board

    return generate_final_calls(events_by_board, verbose=verbose)


def execute_oasm_calls(calls_by_board, assembler_seq=None, clear: bool = True, verbose: bool = False):
    """Compatibility wrapper for OASM execution."""
    return execution.execute_oasm_calls(
        calls_by_board,
        assembler_seq=assembler_seq,
        clear=clear,
        verbose=verbose,
    )
