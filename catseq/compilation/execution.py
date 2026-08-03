"""
Execution helpers for OASM call streams.
"""

import importlib
from collections.abc import Mapping
from typing import Any, Callable, Dict, List, NamedTuple, Protocol, TypeVar

from .functions import (
    rwg_init,
    rwg_load_waveform,
    rwg_play,
    rwg_rf_switch,
    rwg_set_carrier,
    trig_slave,
    ttl_config,
    ttl_set,
    wait_master,
    wait_mu,
    wait_us,
    rsp_init,
    rsp_set_carrier,
    rsp_pid_config,
    rsp_pid_start,
    rsp_pid_hold,
    rsp_pid_release,
    rsp_pid_relink,
    rsp_rf_config,
    loop_begin,
    loop_end,
)
from .types import OASMAddress, OASMCall, OASMFunction
from ..types.rwg import WaveformParams
from ..types.rsp import RSPPIDConfig, RSPWaveformParams

try:
    from oasm.rtmq2 import (
        H,
        asm as oasm_context,
        intf_send,
        nop,
    )

    OASM_AVAILABLE = True
except ImportError:
    OASM_AVAILABLE = False


class _OASMFunctionSpec(NamedTuple):
    """One entry of the single OASM function registry.

    ``plan_name`` is the spelling used by the native OASMCallPlan and is
    ``None`` for operations that only exist in the Python API.
    ``implementation`` is the OASM DSL callable and is ``None`` for operations
    resolved by the host instead of a fixed DSL function.
    """

    function: OASMFunction
    plan_name: str | None
    implementation: Callable | None


_OASM_FUNCTIONS: tuple[_OASMFunctionSpec, ...] = (
    _OASMFunctionSpec(OASMFunction.TTL_CONFIG, "ttl_config", ttl_config),
    _OASMFunctionSpec(OASMFunction.TTL_SET, "ttl_set", ttl_set),
    _OASMFunctionSpec(OASMFunction.WAIT_US, None, wait_us),
    _OASMFunctionSpec(OASMFunction.WAIT, "wait", wait_mu),
    _OASMFunctionSpec(OASMFunction.LOOP_BEGIN, "loop_begin", loop_begin),
    _OASMFunctionSpec(OASMFunction.LOOP_END, "loop_end", loop_end),
    _OASMFunctionSpec(OASMFunction.WAIT_MASTER, "wait_master", wait_master),
    _OASMFunctionSpec(OASMFunction.TRIG_SLAVE, "trig_slave", trig_slave),
    _OASMFunctionSpec(OASMFunction.RWG_INIT, "rwg_init", rwg_init),
    _OASMFunctionSpec(
        OASMFunction.RWG_SET_CARRIER, "rwg_set_carrier", rwg_set_carrier
    ),
    _OASMFunctionSpec(OASMFunction.RWG_RF_SWITCH, "rwg_rf_switch", rwg_rf_switch),
    _OASMFunctionSpec(
        OASMFunction.RWG_LOAD_WAVEFORM, "rwg_load_waveform", rwg_load_waveform
    ),
    _OASMFunctionSpec(OASMFunction.RWG_PLAY, "rwg_play", rwg_play),
    _OASMFunctionSpec(OASMFunction.RSP_INIT, "rsp_init", rsp_init),
    _OASMFunctionSpec(
        OASMFunction.RSP_SET_CARRIER, "rsp_set_carrier", rsp_set_carrier
    ),
    _OASMFunctionSpec(OASMFunction.RSP_PID_CONFIG, "rsp_pid_config", rsp_pid_config),
    _OASMFunctionSpec(OASMFunction.RSP_PID_START, "rsp_pid_start", rsp_pid_start),
    _OASMFunctionSpec(OASMFunction.RSP_PID_HOLD, "rsp_pid_hold", rsp_pid_hold),
    _OASMFunctionSpec(
        OASMFunction.RSP_PID_RELEASE, "rsp_pid_release", rsp_pid_release
    ),
    _OASMFunctionSpec(OASMFunction.RSP_PID_RELINK, "rsp_pid_relink", rsp_pid_relink),
    _OASMFunctionSpec(OASMFunction.RSP_RF_CONFIG, "rsp_rf_config", rsp_rf_config),
    _OASMFunctionSpec(OASMFunction.USER_DEFINED_FUNC, "user_defined_func", None),
)


OASM_FUNCTION_MAP: Dict[OASMFunction, Callable] = {
    spec.function: spec.implementation
    for spec in _OASM_FUNCTIONS
    if spec.implementation is not None
}


_PLAN_FUNCTIONS: Dict[str, OASMFunction] = {
    spec.plan_name: spec.function
    for spec in _OASM_FUNCTIONS
    if spec.plan_name is not None
}


class _OASMAssembler(Protocol):
    asm: Any

    def clear(self) -> Any: ...

    def __call__(
        self,
        address: str,
        function: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any: ...


_AssemblerT = TypeVar("_AssemblerT", bound=_OASMAssembler)


def _decode_plan_value(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_decode_plan_value(item) for item in value)
    if not isinstance(value, dict):
        return value
    record_type = value.get("$type")
    fields = {
        name: _decode_plan_value(field)
        for name, field in value.items()
        if name != "$type"
    }
    if record_type == "WaveformParams":
        return WaveformParams(**fields)
    if record_type == "RSPPIDConfig":
        for name in ("adc_in", "rf_out", "dgt_source"):
            fields[name] = int(fields[name])
        return RSPPIDConfig(**fields)
    if record_type == "RSPWaveformParams":
        fields["rf_out"] = int(fields["rf_out"])
        return RSPWaveformParams(**fields)
    return fields


def decode_oasm_call_plan(
    plan: Mapping[str, Any],
    opaque_callables: Mapping[str, Callable[..., Any]] | None = None,
) -> Dict[OASMAddress, List[OASMCall]]:
    """Convert the Rust compiler's JSON OASMCallPlan into executable calls.

    Epochs are concatenated in ID order.  Each board stream already contains
    the waits needed to realize the call offsets relative to its epoch origin.
    Opaque calls use stable string keys and must be resolved explicitly by the
    host application; no Python object is serialized into the native plan.
    """
    if plan.get("schema_version") != 1:
        raise ValueError(f"Unsupported OASMCallPlan schema: {plan.get('schema_version')!r}")
    opaque_callables = opaque_callables or {}
    calls_by_board: Dict[OASMAddress, List[OASMCall]] = {}
    epochs = sorted(plan.get("epochs", ()), key=lambda epoch: epoch["id"])
    for expected_id, epoch in enumerate(epochs):
        if epoch.get("id") != expected_id:
            raise ValueError("OASMCallPlan epoch IDs must be contiguous and start at zero")
        for board in epoch.get("boards", ()):
            try:
                address = OASMAddress(board["address"])
            except ValueError as error:
                raise ValueError(f"Unknown OASM board address {board['address']!r}") from error
            board_calls = calls_by_board.setdefault(address, [])
            previous_offset = 0
            for raw_call in board.get("calls", ()):
                offset = raw_call["offset_cycles"]
                if offset < previous_offset:
                    raise ValueError(
                        f"OASM calls for {address.value} are not ordered within epoch {expected_id}"
                    )
                previous_offset = offset
                try:
                    function = _PLAN_FUNCTIONS[raw_call["function"]]
                except KeyError as error:
                    raise ValueError(
                        f"Unknown OASM plan function {raw_call['function']!r}"
                    ) from error
                args = tuple(_decode_plan_value(arg) for arg in raw_call.get("args", ()))
                if function == OASMFunction.USER_DEFINED_FUNC:
                    if len(args) != 3 or not isinstance(args[0], str):
                        raise ValueError("Opaque OASM calls require [callable_key, args, kwargs]")
                    callable_key, user_args, user_kwargs = args
                    try:
                        user_func = opaque_callables[callable_key]
                    except KeyError as error:
                        raise ValueError(
                            f"No host callable is registered for opaque key {callable_key!r}"
                        ) from error
                    if not isinstance(user_args, tuple) or not isinstance(user_kwargs, dict):
                        raise ValueError("Opaque OASM call arguments have invalid native shapes")
                    args = (user_func, user_args, user_kwargs)
                board_calls.append(OASMCall(adr=address, dsl_func=function, args=args))
    return calls_by_board


def oasm_call_plan_to_calls(
    plan: Mapping[str, Any],
    opaque_callables: Mapping[str, Callable[..., Any]] | None = None,
) -> Dict[OASMAddress, List[OASMCall]]:
    """Compatibility name for :func:`decode_oasm_call_plan`."""

    return decode_oasm_call_plan(plan, opaque_callables=opaque_callables)


def _submit_oasm_calls(
    calls_by_board: Mapping[OASMAddress, List[OASMCall]],
    assembler_seq: _AssemblerT,
    *,
    clear: bool = True,
    verbose: bool = False,
) -> _AssemblerT:
    """Submit decoded calls without finalizing or executing the assembler."""
    if clear:
        assembler_seq.clear()

    call_counter = 0
    for board_adr, board_calls in calls_by_board.items():
        if verbose:
            print(
                f"📋 Processing {len(board_calls)} calls "
                f"for board '{board_adr.value}':"
            )
        for call in board_calls:
            call_counter += 1
            if call.dsl_func == OASMFunction.USER_DEFINED_FUNC:
                user_func, user_args, user_kwargs = call.args
                if verbose:
                    print(
                        f"  [{call_counter:02d}] Executing black-box function: "
                        f"{user_func.__name__}"
                    )
                assembler_seq(
                    call.adr.value,
                    user_func,
                    *user_args,
                    **user_kwargs,
                )
                continue

            function = OASM_FUNCTION_MAP.get(call.dsl_func)
            if function is None:
                raise ValueError(
                    f"OASM function {call.dsl_func.name!r} is not registered"
                )
            kwargs = call.kwargs or {}
            if verbose:
                args_str = ", ".join(map(str, call.args))
                kwargs_str = (
                    ", ".join(f"{key}={value}" for key, value in kwargs.items())
                    if kwargs
                    else ""
                )
                params_str = ", ".join(filter(None, [args_str, kwargs_str]))
                print(f"  [{call_counter:02d}] {function.__name__}({params_str})")
            assembler_seq(
                call.adr.value,
                function,
                *call.args,
                **kwargs,
            )

    return assembler_seq


def assemble_oasm_calls(
    calls_by_board: Mapping[OASMAddress, List[OASMCall]],
    assembler_seq: _AssemblerT,
    *,
    clear: bool = True,
    verbose: bool = False,
) -> Any:
    """Purely assemble calls into a frozen Rust-owned runtime program.

    OASM remains the instruction encoder.  This function copies each populated
    board context before appending the public OASM completion epilogue, so the
    caller's assembler remains reusable and no download side effect occurs.
    """
    if not OASM_AVAILABLE:
        raise RuntimeError("OASM modules are required to assemble a runtime program")
    if not calls_by_board:
        raise ValueError("cannot assemble an empty OASM call mapping")

    _submit_oasm_calls(
        calls_by_board,
        assembler_seq,
        clear=clear,
        verbose=verbose,
    )

    native = importlib.import_module("catseq._native")
    boards = []
    reply_endpoint: tuple[int, int] | None = None
    for board_address in calls_by_board:
        board_name = board_address.value
        try:
            board_context = assembler_seq.asm[board_name]
        except (AttributeError, KeyError) as error:
            raise ValueError(
                f"assembler has no populated context for board {board_name!r}"
            ) from error

        finalized_context = board_context.copy()
        context_interface = getattr(finalized_context, "intf", None)
        if context_interface is None:
            raise ValueError(
                f"assembler context for board {board_name!r} has no interface"
            )
        try:
            board_reply_endpoint = (
                int(context_interface.nod_adr),
                int(context_interface.loc_chn),
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError(
                f"assembler context for board {board_name!r} "
                "has no valid reply endpoint"
            ) from error
        if reply_endpoint is None:
            reply_endpoint = board_reply_endpoint
        elif reply_endpoint != board_reply_endpoint:
            raise ValueError(
                "all assembled boards must use the same reply endpoint; "
                f"{board_name!r} uses {board_reply_endpoint}, "
                f"expected {reply_endpoint}"
            )

        with oasm_context < finalized_context:
            intf_send(oper=0)
            nop(2, H)
            exception_handler_word = len(oasm_context[:])
            intf_send("lnk", info=1)
            intf_send("exc", info=0)
            nop(2, H)
            ich_words = list(oasm_context[:])

        boards.append(
            native.AssembledOASMBoard(
                board_name,
                ich_words,
                exception_handler_word,
            )
        )

    assert reply_endpoint is not None
    reply_node, reply_channel = reply_endpoint
    return native.AssembledOASMProgram(
        1,
        reply_node,
        reply_channel,
        boards,
    )
