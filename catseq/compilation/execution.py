"""
Execution helpers for OASM call streams.
"""

from collections.abc import Mapping
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    from oasm.rtmq2 import disassembler, assembler
    from oasm.dev.rwg import C_RWG

    OASM_AVAILABLE = True
except ImportError as e:
    print(f"Warning: OASM modules not available: {e}")
    OASM_AVAILABLE = False


OASM_FUNCTION_MAP: Dict[OASMFunction, Callable] = {
    OASMFunction.TTL_CONFIG: ttl_config,
    OASMFunction.TTL_SET: ttl_set,
    OASMFunction.WAIT_US: wait_us,
    OASMFunction.WAIT: wait_mu,
    OASMFunction.LOOP_BEGIN: loop_begin,
    OASMFunction.LOOP_END: loop_end,
    OASMFunction.WAIT_MASTER: wait_master,
    OASMFunction.TRIG_SLAVE: trig_slave,
    OASMFunction.RWG_INIT: rwg_init,
    OASMFunction.RWG_SET_CARRIER: rwg_set_carrier,
    OASMFunction.RWG_RF_SWITCH: rwg_rf_switch,
    OASMFunction.RWG_LOAD_WAVEFORM: rwg_load_waveform,
    OASMFunction.RWG_PLAY: rwg_play,
    OASMFunction.RSP_INIT: rsp_init,
    OASMFunction.RSP_SET_CARRIER: rsp_set_carrier,
    OASMFunction.RSP_PID_CONFIG: rsp_pid_config,
    OASMFunction.RSP_PID_START: rsp_pid_start,
    OASMFunction.RSP_PID_HOLD: rsp_pid_hold,
    OASMFunction.RSP_PID_RELEASE: rsp_pid_release,
    OASMFunction.RSP_PID_RELINK: rsp_pid_relink,
    OASMFunction.RSP_RF_CONFIG: rsp_rf_config,
}


_PLAN_FUNCTIONS = {
    "loop_begin": OASMFunction.LOOP_BEGIN,
    "loop_end": OASMFunction.LOOP_END,
    "ttl_config": OASMFunction.TTL_CONFIG,
    "ttl_set": OASMFunction.TTL_SET,
    "wait": OASMFunction.WAIT,
    "rwg_init": OASMFunction.RWG_INIT,
    "rwg_set_carrier": OASMFunction.RWG_SET_CARRIER,
    "rwg_rf_switch": OASMFunction.RWG_RF_SWITCH,
    "rwg_load_waveform": OASMFunction.RWG_LOAD_WAVEFORM,
    "rwg_play": OASMFunction.RWG_PLAY,
    "wait_master": OASMFunction.WAIT_MASTER,
    "trig_slave": OASMFunction.TRIG_SLAVE,
    "rsp_init": OASMFunction.RSP_INIT,
    "rsp_set_carrier": OASMFunction.RSP_SET_CARRIER,
    "rsp_pid_config": OASMFunction.RSP_PID_CONFIG,
    "rsp_pid_start": OASMFunction.RSP_PID_START,
    "rsp_pid_hold": OASMFunction.RSP_PID_HOLD,
    "rsp_pid_release": OASMFunction.RSP_PID_RELEASE,
    "rsp_pid_relink": OASMFunction.RSP_PID_RELINK,
    "rsp_rf_config": OASMFunction.RSP_RF_CONFIG,
    "user_defined_func": OASMFunction.USER_DEFINED_FUNC,
}


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


def oasm_call_plan_to_calls(
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


def execute_oasm_calls(
    calls_by_board: Dict[OASMAddress, List[OASMCall]],
    assembler_seq: Optional[assembler]=None,
    clear: bool = True,
    verbose: bool = False,
)-> Tuple[bool, Optional[assembler]]:
    """Execute OASM calls and optionally generate RTMQ assembly."""
    if verbose:
        print("\n--- Executing OASM Calls ---")
    if not calls_by_board:
        print("No OASM calls to execute.")
        return True, assembler_seq

    total_calls = sum(len(calls) for calls in calls_by_board.values())
    print(f"Processing {total_calls} OASM calls across {len(calls_by_board)} boards")

    if assembler_seq is not None and OASM_AVAILABLE:
        print("🔧 Generating actual RTMQ assembly...")
        try:
            call_counter = 0
            if clear:
                assembler_seq.clear()

            for board_adr, board_calls in calls_by_board.items():
                print(f"📋 Processing {len(board_calls)} calls for board '{board_adr.value}':")
                for call in board_calls:
                    call_counter += 1
                    if call.dsl_func == OASMFunction.USER_DEFINED_FUNC:
                        user_func, user_args, user_kwargs = call.args
                        if verbose:
                            print(f"  [{call_counter:02d}] Executing black-box function: {user_func.__name__}")
                        assembler_seq(call.adr.value, user_func, *user_args, **user_kwargs)
                        continue

                    func = OASM_FUNCTION_MAP.get(call.dsl_func)
                    if func is None:
                        print(f"Error: OASM function '{call.dsl_func.name}' not found in map.")
                        return False, assembler_seq

                    if verbose:
                        args_str = ", ".join(map(str, call.args))
                        kwargs_str = (
                            ", ".join(f"{k}={v}" for k, v in call.kwargs.items())
                            if call.kwargs
                            else ""
                        )
                        params_str = ", ".join(filter(None, [args_str, kwargs_str]))
                        print(f"  [{call_counter:02d}] {func.__name__}({params_str})")

                    if call.kwargs:
                        assembler_seq(call.adr.value, func, *call.args, **call.kwargs)
                    else:
                        assembler_seq(call.adr.value, func, *call.args)

            for board_adr in calls_by_board.keys():
                board_name = board_adr.value
                if verbose:
                    print(f"\n📋 Generated RTMQ assembly for {board_name}:")
                try:
                    if OASM_AVAILABLE:
                        asm_lines = disassembler(core=C_RWG)(assembler_seq.asm[board_name])
                        if verbose:
                            for line in asm_lines:
                                print(f"   {line}")
                    else:
                        print("   OASM not available for disassembly")
                except KeyError:
                    print(f"   No assembly generated for {board_name}")
                except Exception as e:
                    print(f"   Assembly generation failed: {e}")

            print("\n--- OASM Execution Finished ---")
            return True, assembler_seq
        except Exception as e:
            import traceback

            print(f"❌ OASM execution with assembler_seq failed: {e}")
            traceback.print_exc()
            return False, assembler_seq

    print("⚠️  OASM modules not available or no assembler_seq provided, falling back to mock execution...")
    success = _execute_oasm_calls_mock(calls_by_board)
    return success, None


def _execute_oasm_calls_mock(calls_by_board: Dict[OASMAddress, List[OASMCall]]) -> bool:
    """Mock execution fallback when OASM is not available."""
    try:
        call_counter = 0
        for board_adr, board_calls in calls_by_board.items():
            print(f"\n📋 Mock execution for board '{board_adr.value}' ({len(board_calls)} calls):")
            for call in board_calls:
                call_counter += 1
                if call.dsl_func == OASMFunction.USER_DEFINED_FUNC:
                    user_func, user_args, user_kwargs = call.args
                    user_func(*user_args, **user_kwargs)
                    continue
                func = OASM_FUNCTION_MAP.get(call.dsl_func)
                if func is None:
                    print(f"Error: OASM function '{call.dsl_func.name}' not found in map.")
                    return False

                args_str = ", ".join(map(str, call.args))
                kwargs_str = (
                    ", ".join(f"{k}={v}" for k, v in call.kwargs.items())
                    if call.kwargs
                    else ""
                )
                params_str = ", ".join(filter(None, [args_str, kwargs_str]))
                print(f"  [{call_counter:02d}] {func.__name__}({params_str})")

                if call.kwargs:
                    func(*call.args, **call.kwargs)
                else:
                    func(*call.args)
        return True
    except Exception as e:
        import traceback

        print(f"Mock execution failed: {e}")
        traceback.print_exc()
        return False
