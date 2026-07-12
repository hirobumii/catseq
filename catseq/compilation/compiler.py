"""
Compiler orchestration for Morphism -> OASM call translation.
"""

from typing import Mapping

from ..morphism.arena import ArenaProgram
from ..morphism.core import Morphism
from . import execution
from .dag import CompilerSession
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
    morphism: Morphism | ArenaProgram,
    assembler_seq: object | None = None,
    _return_internal_events: bool = False,
    verbose: bool = False,
    bindings: Mapping[str, object] | None = None,
) -> dict[OASMAddress, list[OASMCall]] | dict[OASMAddress, list[LogicalEvent]]:
    """Compile a morphism into scheduled OASM calls."""
    if isinstance(morphism, ArenaProgram) or (
        isinstance(morphism, Morphism) and not _return_internal_events
    ):
        if _return_internal_events:
            raise TypeError(
                "DAG-native compilation does not expose mutable LogicalEvent internals"
            )
        program = (
            morphism.arena_program
            if isinstance(morphism, Morphism)
            else morphism
        )
        try:
            result = CompilerSession(
                program,
                assembler_seq,
                verbose=verbose,
            ).bind(bindings or {})
        except KeyError as error:
            if isinstance(morphism, Morphism) and not bindings:
                raise TypeError(
                    "compile_to_oasm_calls requires a fully concrete morphism. "
                    "Pass bindings or call realize_morphism(...) first."
                ) from error
            raise
        return {
            address: list(board_calls)
            for address, board_calls in result.calls_by_board.items()
        }
    if bindings:
        raise TypeError(
            "bindings are unavailable when returning mutable internal events"
        )
    events_by_board = extract_and_translate(morphism, verbose=verbose)
    analyze_costs_and_epochs(events_by_board, assembler_seq, verbose=verbose)
    schedule_and_optimize(events_by_board, verbose=verbose)
    validate_constraints(events_by_board, verbose=verbose)

    if _return_internal_events:
        return events_by_board

    return generate_final_calls(events_by_board, verbose=verbose)


def execute_oasm_calls(
    calls_by_board: dict[OASMAddress, list[OASMCall]],
    assembler_seq: object | None = None,
    clear: bool = True,
    verbose: bool = False,
) -> tuple[bool, object | None]:
    """Compatibility wrapper for OASM execution."""
    return execution.execute_oasm_calls(
        calls_by_board,
        assembler_seq=assembler_seq,
        clear=clear,
        verbose=verbose,
    )
