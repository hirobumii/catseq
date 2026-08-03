"""Thin Python facade over the Rust-owned physical OASM runtime."""

from __future__ import annotations

from typing import Any

from .. import _native
from .._native import CompiledSequence


AssembledOASMBoard = _native.AssembledOASMBoard
AssembledOASMProgram = _native.AssembledOASMProgram
BoardEndpoint = _native.BoardEndpoint
LinuxRawEthernetRuntimeConfig = _native.LinuxRawEthernetRuntimeConfig
OASMRuntimeSuccess = _native.OASMRuntimeSuccess
OASMRuntimeFailure = _native.OASMRuntimeFailure


class EthernetRuntime:
    """Reusable physical runtime with private OASM instruction encoding."""

    def __init__(
        self,
        *,
        interface: str,
        destination: str,
        reply: tuple[int, int],
        boards: dict[str, int],
        timeout_margin_ms: int = 10_000,
    ) -> None:
        self._backend = _native.EthernetRuntimeBackend(
            interface,
            destination,
            reply,
            boards,
            timeout_margin_ms,
        )

    @property
    def interface(self) -> str:
        return self._backend.interface

    @property
    def destination(self) -> str:
        return self._backend.destination

    @property
    def reply(self) -> tuple[int, int]:
        return self._backend.reply

    @property
    def boards(self) -> dict[str, int]:
        return self._backend.boards

    @property
    def timeout_margin_ms(self) -> int:
        return self._backend.timeout_margin_ms

    def run(
        self,
        compiled: CompiledSequence,
        *,
        timeout_ms: int | None = None,
    ) -> Any:
        """Encode, download, launch, and monitor one CompiledSequence."""

        if not isinstance(compiled, _native.CompiledSequence):
            raise TypeError("EthernetRuntime.run requires a CompiledSequence")
        from ._oasm_encoder import encode_compiled_sequence

        program = encode_compiled_sequence(compiled, reply=self.reply)
        outcome = self._backend.execute(
            program,
            compiled.logical_duration_cycles,
            compiled.clock_hz,
            timeout_ms,
        )
        return _unwrap_outcome(outcome)


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

    return _unwrap_outcome(_native.execute_oasm_program(program, config))


def _unwrap_outcome(outcome: Any) -> Any:
    if isinstance(outcome, OASMRuntimeFailure):
        raise CatSeqRuntimeError(outcome)
    if not isinstance(outcome, OASMRuntimeSuccess):
        raise TypeError(
            "native execute_oasm_program returned an unknown outcome "
            f"{type(outcome)!r}"
        )
    return outcome
