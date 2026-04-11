"""
Execution helpers for OASM call streams.
"""

from typing import Callable, Dict, List

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
)
from .types import OASMAddress, OASMCall, OASMFunction

try:
    from oasm.rtmq2 import disassembler
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
    OASMFunction.WAIT_MASTER: wait_master,
    OASMFunction.TRIG_SLAVE: trig_slave,
    OASMFunction.RWG_INIT: rwg_init,
    OASMFunction.RWG_SET_CARRIER: rwg_set_carrier,
    OASMFunction.RWG_RF_SWITCH: rwg_rf_switch,
    OASMFunction.RWG_LOAD_WAVEFORM: rwg_load_waveform,
    OASMFunction.RWG_PLAY: rwg_play,
}


def execute_oasm_calls(
    calls_by_board: Dict[OASMAddress, List[OASMCall]],
    assembler_seq=None,
    clear: bool = True,
    verbose: bool = False,
):
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
