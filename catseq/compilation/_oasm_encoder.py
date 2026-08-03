"""Private bridge from a native call plan to pinned OASM instruction encoding."""

from __future__ import annotations

from typing import Any

from oasm.dev.main import C_MAIN  # type: ignore[import-untyped]
from oasm.dev.rsp import C_RSP  # type: ignore[import-untyped]
from oasm.dev.rwg import C_RWG  # type: ignore[import-untyped]
from oasm.rtmq2 import assembler  # type: ignore[import-untyped]

from .execution import assemble_oasm_calls, decode_oasm_call_plan
from .types import OASMAddress


class _ReplyInterface:
    """Minimal private shape consumed by OASM's ``intf_send`` encoder."""

    __slots__ = ("loc_chn", "nod_adr")

    def __init__(self, node: int, channel: int) -> None:
        self.nod_adr = node
        self.loc_chn = channel


def encode_compiled_sequence(
    compiled: Any,
    *,
    reply: tuple[int, int],
) -> Any:
    """Encode one immutable CompiledSequence without exposing OASM objects."""

    calls_by_board = decode_oasm_call_plan(
        compiled.oasm_call_plan,
        opaque_callables=compiled._opaque_callables,
    )
    board_cores = [
        (address.value, _core_for(address)) for address in calls_by_board
    ]
    sequence = assembler(multi=board_cores)
    reply_interface = _ReplyInterface(*reply)
    for address in calls_by_board:
        sequence.asm[address.value].intf = reply_interface
    return assemble_oasm_calls(calls_by_board, sequence)


def _core_for(address: OASMAddress) -> Any:
    if address is OASMAddress.MAIN:
        return C_MAIN
    if address.name.startswith("RWG"):
        return C_RWG
    if address.name.startswith("RSP"):
        return C_RSP
    raise ValueError(f"no OASM core is registered for {address.value!r}")
