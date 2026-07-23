"""Thin Python facade over the Rust-owned physical OASM runtime."""

from __future__ import annotations

import importlib
from typing import Any


_native = importlib.import_module("catseq._native")

AssembledOASMBoard = _native.AssembledOASMBoard
AssembledOASMProgram = _native.AssembledOASMProgram
BoardEndpoint = _native.BoardEndpoint
LinuxRawEthernetRuntimeConfig = _native.LinuxRawEthernetRuntimeConfig
OASMRuntimeSuccess = _native.OASMRuntimeSuccess
OASMRuntimeFailure = _native.OASMRuntimeFailure


class CatSeqRuntimeError(RuntimeError):
    """Physical runtime failure with the complete Rust evidence attached."""

    def __init__(self, failure: Any) -> None:
        self.failure = failure
        super().__init__(f"{failure.code}: {failure.message}")

    @property
    def code(self) -> str:
        return self.failure.code

    @property
    def execution_certainty(self) -> str:
        return self.failure.execution_certainty

    @property
    def board_evidence(self) -> dict[str, str]:
        return self.failure.board_evidence

    @property
    def device_exceptions(self) -> dict[str, tuple[int, int | None]]:
        return self.failure.device_exceptions

    @property
    def details(self) -> dict[str, str]:
        return self.failure.details


def execute_oasm_program(program: Any, config: Any) -> Any:
    """Download and monitor one assembled program through the Rust runtime."""

    outcome = _native.execute_oasm_program(program, config)
    if isinstance(outcome, OASMRuntimeFailure):
        raise CatSeqRuntimeError(outcome)
    if not isinstance(outcome, OASMRuntimeSuccess):
        raise TypeError(
            "native execute_oasm_program returned an unknown outcome "
            f"{type(outcome)!r}"
        )
    return outcome
