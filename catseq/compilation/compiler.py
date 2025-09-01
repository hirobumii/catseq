"""
OASM compiler for converting Morphism objects to OASM DSL calls.

This module provides the compilation logic for translating high-level
Morphism objects into concrete OASM DSL function calls. It uses a multi-pass
architecture to support pipelined operations and timing checks.
"""

from dataclasses import dataclass
from typing import List, Dict, Callable

from ..types.common import OperationType, AtomicMorphism
from ..lanes import merge_board_lanes
from ..types.rwg import RWGWaveformInstruction
from ..time_utils import cycles_to_us
from .types import OASMAddress, OASMFunction, OASMCall
from .functions import (
    ttl_config,
    ttl_set,
    wait_us,
    rwg_initialize_port,
    rwg_rf_switch,
    rwg_load_waveform,
    rwg_play,
)

# Import OASM modules for actual assembly generation
try:
    from oasm.rtmq2 import disassembler
    from oasm.dev.rwg import C_RWG
    OASM_AVAILABLE = True
except ImportError as e:
    print(f"Warning: OASM modules not available: {e}")
    OASM_AVAILABLE = False

# --- Compiler Data Structures ---

@dataclass
class LogicalEvent:
    """Internal representation of a single logical operation on the timeline."""
    timestamp_cycles: int
    operation: AtomicMorphism
    cost_cycles: int = 0

# --- Main Compiler Entry Point ---

def compile_to_oasm_calls(morphism, _return_internal_events=False) -> List[OASMCall]:
    """Drives the multi-pass compilation process."""
    
    # Pass 0: Extract a flat list of events from the morphism, grouped by board.
    events_by_board = _pass0_extract_events(morphism)
    
    # Pass 1: Analyze costs of expensive operations.
    _pass1_analyze_costs(events_by_board)
    
    # Pass 2: Check for timing violations (e.g., pipelining constraints).
    _pass2_check_constraints(events_by_board)

    # For testing purposes, allow returning the internal event list
    if _return_internal_events:
        return events_by_board
    
    # Pass 3: Generate the final, scheduled OASM calls.
    oasm_calls = _pass3_generate_oasm_calls(events_by_board)
    
    return oasm_calls

# --- Compiler Passes ---

def _pass0_extract_events(morphism) -> Dict[OASMAddress, List[LogicalEvent]]:
    """Pass 0: Flattens the morphism into a time-sorted list of LogicalEvents per board."""
    events_by_board: Dict[OASMAddress, List[LogicalEvent]] = {}

    for board, board_lanes in morphism.lanes_by_board().items():
        try:
            adr = OASMAddress(board.id.lower())
        except ValueError:
            print(f"Warning: Board ID '{board.id}' not found in OASMAddress enum. Defaulting to RWG0.")
            adr = OASMAddress.RWG0

        if adr not in events_by_board:
            events_by_board[adr] = []

        physical_lane = merge_board_lanes(board, board_lanes)
        for pop in physical_lane.operations:
            event = LogicalEvent(
                timestamp_cycles=pop.timestamp_cycles,
                operation=pop.operation
            )
            events_by_board[adr].append(event)
    
    for adr in events_by_board:
        events_by_board[adr].sort(key=lambda e: e.timestamp_cycles)
        
    return events_by_board

def _pass1_analyze_costs(events_by_board: Dict[OASMAddress, List[LogicalEvent]]):
    """Pass 1: Annotates events with their execution cost in cycles."""
    print("Compiler Pass 1: Analyzing costs...")
    for adr, events in events_by_board.items():
        for event in events:
            print(f"  - Analyzing event: {event.operation.operation_type.name}") # DEBUG PRINT
            if event.operation.operation_type == OperationType.RWG_LOAD_COEFFS:
                # Placeholder cost model: 20 cycles per parameter.
                # The end_state of a LOAD op is RWGWaveformInstruction.
                if isinstance(event.operation.end_state, RWGWaveformInstruction):
                    num_params = len(event.operation.end_state.params)
                    event.cost_cycles = num_params * 20
                    print(f"    - Cost for LOAD at {event.timestamp_cycles} on {adr.value}: {event.cost_cycles} cycles")

def _pass2_check_constraints(events_by_board: Dict[OASMAddress, List[LogicalEvent]]):
    """Pass 2: Checks for timing violations, such as pipelining."""
    print("Compiler Pass 2: Checking constraints...")
    for adr, events in events_by_board.items():
        # Group events by channel to check sequences correctly
        events_by_channel: Dict[int, List[LogicalEvent]] = {}
        for event in events:
            if event.operation.channel:
                cid = event.operation.channel.local_id
                if cid not in events_by_channel:
                    events_by_channel[cid] = []
                events_by_channel[cid].append(event)

        for cid, channel_events in events_by_channel.items():
            for i, event in enumerate(channel_events):
                if event.operation.operation_type == OperationType.RWG_UPDATE_PARAMS:
                    play_op = event.operation
                    play_duration = play_op.duration_cycles

                    if play_duration > 0:
                        # Find the next load operation on the same channel
                        next_load_event = None
                        for j in range(i + 1, len(channel_events)):
                            if channel_events[j].operation.operation_type == OperationType.RWG_LOAD_COEFFS:
                                next_load_event = channel_events[j]
                                break
                        
                        if next_load_event:
                            load_cost = next_load_event.cost_cycles
                            if play_duration < load_cost:
                                raise ValueError(
                                    f"Timing violation on board {adr.value}, channel {cid}: "
                                    f"Waveform segment at {event.timestamp_cycles} cycles has duration {play_duration} cycles, "
                                    f"but the next parameter load requires {load_cost} cycles."
                                )
                            print(f"  - OK: Play at {event.timestamp_cycles} ({play_duration}c) >= Load at {next_load_event.timestamp_cycles} ({load_cost}c)")

def _pass3_generate_oasm_calls(events_by_board: Dict[OASMAddress, List[LogicalEvent]]) -> List[OASMCall]:
    """Pass 3: Generates the final scheduled OASM calls from the logical events."""
    print("Compiler Pass 3: Generating and scheduling OASM calls...")
    all_calls: List[OASMCall] = []

    for adr, events in events_by_board.items():
        events_by_ts: Dict[int, List[LogicalEvent]] = {}
        for event in events: 
            if event.timestamp_cycles not in events_by_ts: events_by_ts[event.timestamp_cycles] = []
            events_by_ts[event.timestamp_cycles].append(event)

        previous_ts = 0
        pipelined_load_cost = 0
        sorted_timestamps = sorted(events_by_ts.keys())

        for i, timestamp in enumerate(sorted_timestamps):
            # Adjust wait time for any pipelined loads from the previous segment
            wait_cycles = timestamp - previous_ts - pipelined_load_cost
            if wait_cycles < 0:
                # This should be caught by Pass 2, but as a safeguard:
                raise ValueError(f"Negative wait time calculated at timestamp {timestamp}. This indicates a timing violation.")
            if wait_cycles > 0:
                all_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.WAIT_US, args=(cycles_to_us(wait_cycles),)))
            
            pipelined_load_cost = 0 # Reset cost for current timestamp
            
            ops_by_type: Dict[OperationType, List[AtomicMorphism]] = {}
            for event in events_by_ts[timestamp]:
                op_type = event.operation.operation_type
                if op_type not in ops_by_type: ops_by_type[op_type] = []
                ops_by_type[op_type].append(event.operation)

            # --- Generate calls for current timestamp ---
            # TTL and non-pipelined RWG ops
            if OperationType.TTL_INIT in ops_by_type:
                mask, dir_value = 0, 0
                for op in ops_by_type[OperationType.TTL_INIT]:
                    mask |= (1 << op.channel.local_id)
                    if op.end_state.value == 1: dir_value |= (1 << op.channel.local_id)
                all_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.TTL_CONFIG, args=(mask, dir_value)))
            
            if OperationType.TTL_ON in ops_by_type or OperationType.TTL_OFF in ops_by_type:
                mask, state_value = 0, 0
                for op in ops_by_type.get(OperationType.TTL_ON, []): mask |= (1 << op.channel.local_id); state_value |= (1 << op.channel.local_id)
                for op in ops_by_type.get(OperationType.TTL_OFF, []): mask |= (1 << op.channel.local_id)
                if mask > 0: all_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.TTL_SET, args=(mask, state_value)))

            if OperationType.RWG_INIT in ops_by_type:
                for op in ops_by_type[OperationType.RWG_INIT]:
                    all_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.RWG_INITIALIZE_PORT, args=(op.channel.local_id, op.end_state.carrier_freq)))

            if OperationType.RWG_RF_SWITCH in ops_by_type:
                on_mask = 0
                for op in ops_by_type[OperationType.RWG_RF_SWITCH]:
                    if op.end_state.rf_on: on_mask |= (1 << op.channel.local_id)
                all_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.RWG_RF_SWITCH, args=(on_mask,)))

            # Handle PLAY operations and schedule subsequent LOADs
            if OperationType.RWG_UPDATE_PARAMS in ops_by_type:
                pud_mask, iou_mask = 0, 0
                play_ops = ops_by_type[OperationType.RWG_UPDATE_PARAMS]
                duration_us = cycles_to_us(play_ops[0].duration_cycles)
                playing_channels = {op.channel.local_id for op in play_ops}
                
                for op in play_ops: 
                    pud_mask |= (1 << op.channel.local_id)
                    iou_mask |= (1 << op.channel.local_id)
                all_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.RWG_PLAY, args=(duration_us, pud_mask, iou_mask)))

                # --- Pipelining Logic ---
                next_ts_index = i + 1
                if next_ts_index < len(sorted_timestamps):
                    next_timestamp = sorted_timestamps[next_ts_index]
                    for next_event in events_by_ts[next_timestamp]:
                        if next_event.operation.operation_type == OperationType.RWG_LOAD_COEFFS and next_event.operation.channel.local_id in playing_channels:
                            if isinstance(next_event.operation.end_state, RWGWaveformInstruction):
                                for params in next_event.operation.end_state.params:
                                    all_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.RWG_LOAD_WAVEFORM, args=(params,)))
                                pipelined_load_cost += next_event.cost_cycles

            # Don't generate calls for LOAD_COEFFS here, as they are handled by the pipelining logic.

            previous_ts = timestamp

    return all_calls

# Map OASMFunction enum members to actual OASM DSL functions
OASM_FUNCTION_MAP: Dict[OASMFunction, Callable] = {
    OASMFunction.TTL_CONFIG: ttl_config,
    OASMFunction.TTL_SET: ttl_set,
    OASMFunction.WAIT_US: wait_us,
    OASMFunction.RWG_INITIALIZE_PORT: rwg_initialize_port,
    OASMFunction.RWG_RF_SWITCH: rwg_rf_switch,
    OASMFunction.RWG_LOAD_WAVEFORM: rwg_load_waveform,
    OASMFunction.RWG_PLAY: rwg_play,
}

def execute_oasm_calls(calls: List[OASMCall], seq=None):
    """执行 OASM 调用序列并生成实际的 RTMQ 汇编代码"""
    print("\n--- Executing OASM Calls ---")
    if not calls:
        print("No OASM calls to execute.")
        return True, seq
    
    if seq is not None and OASM_AVAILABLE:
        print("🔧 Generating actual RTMQ assembly...")
        try:
            for i, call in enumerate(calls):
                func = OASM_FUNCTION_MAP.get(call.dsl_func)
                if func is None:
                    print(f"Error: OASM function '{call.dsl_func.name}' not found in map.")
                    return False, seq
                
                args_str = ", ".join(map(str, call.args))
                kwargs_str = ", ".join(f"{k}={v}" for k, v in call.kwargs.items())
                params_str = ", ".join(filter(None, [args_str, kwargs_str]))
                print(f"[{i+1:02d}] Board '{call.adr.value}': Calling {func.__name__}({params_str})")
                
                seq(call.adr.value, func, *call.args, **call.kwargs)
            
            board_names = set(call.adr.value for call in calls)
            for board_name in board_names:
                print(f"\n📋 Generated RTMQ assembly for {board_name}:")
                try:
                    asm_lines = disassembler(core=C_RWG)(seq.asm[board_name])
                    for line in asm_lines:
                        print(f"   {line}")
                except KeyError:
                    print(f"   No assembly generated for {board_name}")
                except Exception as e:
                    print(f"   Assembly generation failed: {e}")
            
            print("\n--- OASM Execution Finished ---")
            return True, seq
            
        except Exception as e:
            import traceback
            print(f"❌ OASM execution with seq failed: {e}")
            traceback.print_exc()
            return False, seq
    else:
        print("⚠️  OASM modules not available or no seq object provided, falling back to mock execution...")
        success = _execute_oasm_calls_mock(calls)
        return success, None

def _execute_oasm_calls_mock(calls: List[OASMCall]) -> bool:
    """Mock execution fallback when OASM is not available"""
    try:
        for i, call in enumerate(calls):
            func = OASM_FUNCTION_MAP.get(call.dsl_func)
            if func is None:
                print(f"Error: OASM function '{call.dsl_func.name}' not found in map.")
                return False
            
            args_str = ", ".join(map(str, call.args))
            kwargs_str = ", ".join(f"{k}={v}" for k, v in call.kwargs.items())
            params_str = ", ".join(filter(None, [args_str, kwargs_str]))
            print(f"[{i+1:02d}] Board '{call.adr.value}': Calling {func.__name__}({params_str})")
            
            func(*call.args, **call.kwargs)
            
        return True
    except Exception as e:
        import traceback
        print(f"Mock execution failed: {e}")
        traceback.print_exc()
        return False