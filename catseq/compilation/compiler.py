"""
OASM compiler for converting Morphism objects to OASM DSL calls.

This module provides the compilation logic for translating high-level
Morphism objects into concrete OASM DSL function calls. It uses a multi-pass
architecture to support pipelined operations and timing checks.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Callable

from ..types.common import OperationType, AtomicMorphism, Channel
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

# Import OASM modules only for disassembly in cost analysis
try:
    from oasm.rtmq2 import disassembler
    from oasm.dev.rwg import C_RWG
    OASM_AVAILABLE = True
except ImportError as e:
    print(f"Warning: OASM modules not available: {e}")
    OASM_AVAILABLE = False

# --- Cost Analysis Data ---

# Based on RTMQv2 ISA, assuming most instructions take 1 cycle.
# This is a configurable assumption and may change with hardware implementation.
RTMQ_INSTRUCTION_COSTS = {
    # Default cost for unknown instructions will be 1
    'CHI': 1, 'CLO': 1, 'AMK': 1, 'SFS': 1, 'NOP': 1,
    'CSR': 1, 'GHI': 1, 'GLO': 1, 'OPL': 1,
    'PLO': 4,  # Multiplication, estimated cost
    'PHI': 4,  # Multiplication, estimated cost
    'DIV': 8,  # Division, estimated cost
    'MOD': 8,  # Division, estimated cost
    'AND': 1, 'IAN': 1, 'BOR': 1, 'XOR': 1, 'SGN': 1,
    'ADD': 1, 'SUB': 1, 'CAD': 1, 'CSB': 1, 'NEQ': 1,
    'EQU': 1, 'LST': 1, 'LSE': 1, 'SHL': 1, 'SHR': 1,
    'ROL': 1, 'SAR': 1,
}

# --- Compiler Data Structures ---

@dataclass
class LogicalEvent:
    """
    Internal representation of a single logical operation on the timeline.
    This dataclass is progressively enriched by the compiler passes.
    """
    timestamp_cycles: int
    operation: AtomicMorphism
    
    # Populated by Pass 1 (Translation)
    oasm_calls: List[OASMCall] = field(default_factory=list)
    
    # Populated by Pass 2 (Cost Analysis)
    cost_cycles: int = 0

# --- Main Compiler Entry Point ---

def compile_to_oasm_calls(morphism, assembler_seq=None, _return_internal_events=False) -> List[OASMCall]:
    """Drives the four-pass compilation process.
    
    Args:
        morphism: The morphism to compile
        assembler_seq: Pre-initialized OASM assembler sequence for cost analysis.
                      If None, cost analysis will be skipped when OASM is not available.
        _return_internal_events: For testing, return internal events instead of calls
    """
    
    # Pass 0: Decompose the Morphism into a flat list of logical "nodes".
    events_by_board = _pass0_extract_events(morphism)
    
    # Pass 1: Translate each logical node's intent into concrete OASM calls.
    _pass1_translate_to_oasm(events_by_board)
    
    # Pass 2: Analyze the cost of expensive operations using the translated calls.
    _pass2_analyze_costs(events_by_board, assembler_seq)
    
    # Pass 3: Check for timing violations (e.g., pipelining constraints).
    _pass3_check_constraints(events_by_board)

    # For testing purposes, allow returning the internal event list
    if _return_internal_events:
        return events_by_board
    
    # Pass 4: Generate the final, scheduled OASM calls including waits.
    oasm_calls = _pass4_generate_oasm_calls(events_by_board)
    
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

# --- Helper Functions for Cost Analysis ---

def _get_oasm_calls_for_load(operation: AtomicMorphism, adr: OASMAddress) -> List[OASMCall]:
    """Generates the list of OASMCalls for a RWG_LOAD_COEFFS operation."""
    calls = []
    if isinstance(operation.end_state, RWGWaveformInstruction):
        for params in operation.end_state.params:
            calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.RWG_LOAD_WAVEFORM, args=(params,)))
    return calls

def _estimate_oasm_cost(assembly_lines: List[str]) -> int:
    """Analyzes a list of RTMQ assembly lines to calculate total cycle cost."""
    total_cost = 0
    for line in assembly_lines:
        # Example line: "0000: 09010000    CLO - &01 0x00000"
        parts = line.strip().split()
        if len(parts) < 3:
            continue # Not a valid instruction line
        
        instruction = parts[2].upper()
        cost = RTMQ_INSTRUCTION_COSTS.get(instruction, 1) # Default to 1 cycle
        total_cost += cost
        
        # Check for 'P' flag, which adds a pause cost.
        # The exact cost is implementation-defined; we'll estimate it as 4 cycles.
        if len(parts) > 3 and parts[3].upper() == 'P':
            total_cost += 4 # Estimated pause cost
            
    return total_cost

def _pass1_translate_to_oasm(events_by_board: Dict[OASMAddress, List[LogicalEvent]]):
    """
    Pass 1: Translates the abstract intent of each LogicalEvent into a list
    of concrete OASMCall objects, stored within the event itself.
    """
    print("Compiler Pass 1: Translating logical events to OASM calls...")
    for adr, events in events_by_board.items():
        # Group events by timestamp to handle simultaneous operations that might be merged
        events_by_ts: Dict[int, List[LogicalEvent]] = {}
        for event in events:
            if event.timestamp_cycles not in events_by_ts:
                events_by_ts[event.timestamp_cycles] = []
            events_by_ts[event.timestamp_cycles].append(event)

        for ts, ts_events in events_by_ts.items():
            ops_by_type: Dict[OperationType, List[AtomicMorphism]] = {}
            for event in ts_events:
                op_type = event.operation.operation_type
                if op_type not in ops_by_type: ops_by_type[op_type] = []
                ops_by_type[op_type].append(event.operation)

            # --- OASM Call Generation Logic ---
            
            # Handle 1-to-1 translations using a match statement for clarity
            for event in ts_events:
                op = event.operation
                match op.operation_type:
                    case OperationType.RWG_INIT:
                        event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.RWG_INITIALIZE_PORT, args=(op.channel.local_id, op.end_state.carrier_freq)))
                    
                    case OperationType.RWG_RF_SWITCH:
                        on_mask = (1 << op.channel.local_id) if op.end_state.rf_on else 0
                        event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.RWG_RF_SWITCH, args=(on_mask,)))

                    case OperationType.RWG_LOAD_COEFFS:
                        # Generate separate OASM calls for each WaveformParams in the instruction
                        # The OASM DSL function expects individual WaveformParams, not the entire instruction
                        if isinstance(op.end_state, RWGWaveformInstruction):
                            for waveform_params in op.end_state.params:
                                event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.RWG_LOAD_WAVEFORM, args=(waveform_params,)))
                    
                    case _:
                        # This operation is either a merged operation or doesn't translate to a call.
                        pass

            # Handle many-to-1 (merged) translations
            if OperationType.TTL_INIT in ops_by_type:
                mask, dir_value = 0, 0
                for op in ops_by_type[OperationType.TTL_INIT]:
                    mask |= (1 << op.channel.local_id)
                    if op.end_state.value == 1: dir_value |= (1 << op.channel.local_id)
                
                for event in ts_events:
                    if event.operation.operation_type == OperationType.TTL_INIT:
                        event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.TTL_CONFIG, args=(mask, dir_value)))
                        break # Store the single merged call in the first relevant event
            
            if OperationType.TTL_ON in ops_by_type or OperationType.TTL_OFF in ops_by_type:
                mask, state_value = 0, 0
                for op in ops_by_type.get(OperationType.TTL_ON, []): mask |= (1 << op.channel.local_id); state_value |= (1 << op.channel.local_id)
                for op in ops_by_type.get(OperationType.TTL_OFF, []): mask |= (1 << op.channel.local_id)
                if mask > 0:
                    for event in ts_events:
                        if event.operation.operation_type in [OperationType.TTL_ON, OperationType.TTL_OFF]:
                            event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.TTL_SET, args=(mask, state_value)))
                            break # Store the single merged call in the first relevant event

            if OperationType.RWG_UPDATE_PARAMS in ops_by_type:
                pud_mask, iou_mask = 0, 0
                play_ops = ops_by_type[OperationType.RWG_UPDATE_PARAMS]
                duration_us = cycles_to_us(play_ops[0].duration_cycles)
                
                for op in play_ops: 
                    pud_mask |= (1 << op.channel.local_id)
                    iou_mask |= (1 << op.channel.local_id)
                
                for event in ts_events:
                    if event.operation.operation_type == OperationType.RWG_UPDATE_PARAMS:
                        event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.RWG_PLAY, args=(pud_mask, iou_mask)))
                        break # Store the single merged call in the first relevant event


def _pass2_analyze_costs(events_by_board: Dict[OASMAddress, List[LogicalEvent]], assembler_seq=None):
    """
    Pass 2: Annotates events with their execution cost in cycles by analyzing
    the OASM calls generated in Pass 1.
    
    Args:
        events_by_board: Events organized by board
        assembler_seq: Pre-initialized OASM assembler sequence. If None, cost analysis is skipped.
    """
    print("Compiler Pass 2: Analyzing costs via assembly generation...")
    
    if assembler_seq is None:
        if OASM_AVAILABLE:
            print("Warning: No assembler provided. Cost analysis will be skipped.")
        else:
            print("Warning: OASM modules not available. Skipping cost analysis.")
        return

    for adr, events in events_by_board.items():
        for event in events:
            # We only need to analyze operations that have a non-zero cost,
            # typically pipelined LOAD operations.
            if event.operation.operation_type == OperationType.RWG_LOAD_COEFFS:
                if not event.oasm_calls:
                    print(f"    - Warning: No OASM calls found for LOAD at {event.timestamp_cycles} on {adr.value}. Cost set to 0.")
                    event.cost_cycles = 0
                    continue
                # Clear assembler state for clean cost analysis
                assembler_seq.clear()
                
                # Execute OASM calls to generate assembly
                for call in event.oasm_calls:
                    func = OASM_FUNCTION_MAP.get(call.dsl_func)
                    if func:
                        if call.kwargs:
                            assembler_seq(call.adr.value, func, *call.args, **call.kwargs)
                        else:
                            assembler_seq(call.adr.value, func, *call.args)

                # Check if assembly was generated (note: OASM uses .asm.multi structure)
                if adr.value in assembler_seq.asm.multi:
                    binary_asm = assembler_seq.asm[adr.value]
                    asm_lines = disassembler(core=C_RWG)(binary_asm)
                    
                    cost = _estimate_oasm_cost(asm_lines)
                    event.cost_cycles = cost
                    print(f"    - Cost for LOAD at {event.timestamp_cycles} on {adr.value}: {cost} cycles (from assembly)")
                else:
                    event.cost_cycles = 0
                    print(f"    - Warning: No assembly generated for LOAD at {event.timestamp_cycles} on {adr.value}. Cost set to 0.")


def _pass3_check_constraints(events_by_board: Dict[OASMAddress, List[LogicalEvent]]):
    """Pass 3: Checks for timing violations, such as pipelining."""
    print("Compiler Pass 3: Checking constraints...")
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

@dataclass(frozen=True)
class PipelinePair:
    """A LOAD-PLAY operation pair for pipelining optimization."""
    load_event: 'LogicalEvent'
    play_event: 'LogicalEvent'
    
    @property
    def channel(self) -> Channel:
        """The channel this pair operates on."""
        return self.load_event.operation.channel
    
    @property
    def load_cost_cycles(self) -> int:
        """Cost in cycles for the LOAD operation."""
        return self.load_event.cost_cycles
    
    @property
    def play_start_time(self) -> int:
        """Start time for the PLAY operation."""
        return self.play_event.timestamp_cycles


def _identify_pipeline_pairs(events: List[LogicalEvent]) -> List[PipelinePair]:
    """
    Identify pipeline pairs (LOAD → PLAY sequences) for optimization.
    
    A pipeline pair consists of:
    1. A LOAD event (RWG_LOAD_COEFFS)
    2. The next PLAY event (RWG_UPDATE_PARAMS) on the same channel
    
    Args:
        events: List of LogicalEvent sorted by timestamp
        
    Returns:
        List of PipelinePair objects representing LOAD→PLAY sequences
    """
    pairs = []
    
    # Group events by channel for efficient lookup
    events_by_channel: Dict[Channel, List[LogicalEvent]] = {}
    for event in events:
        channel = event.operation.channel
        if channel not in events_by_channel:
            events_by_channel[channel] = []
        events_by_channel[channel].append(event)
    
    # For each channel, find LOAD→PLAY pairs
    for channel, channel_events in events_by_channel.items():
        # Sort by timestamp to ensure proper ordering
        channel_events.sort(key=lambda e: e.timestamp_cycles)
        
        for i, event in enumerate(channel_events):
            if event.operation.operation_type == OperationType.RWG_LOAD_COEFFS:
                # Look for the next UPDATE_PARAMS on the same channel
                for j in range(i + 1, len(channel_events)):
                    next_event = channel_events[j]
                    if next_event.operation.operation_type == OperationType.RWG_UPDATE_PARAMS:
                        # Found the corresponding PLAY event
                        pair = PipelinePair(load_event=event, play_event=next_event)
                        pairs.append(pair)
                        print(f"    Found pipeline pair: LOAD@{event.timestamp_cycles}c → PLAY@{next_event.timestamp_cycles}c on {channel.global_id}")
                        break
    
    return pairs


def _calculate_optimal_schedule(events: List[LogicalEvent], pipeline_pairs: List[PipelinePair]) -> List[LogicalEvent]:
    """
    Calculate optimal scheduling for pipeline pairs to minimize wait times.
    
    This function implements cross-channel pipelining optimization:
    - LOAD operations can be rescheduled to execute during other channels' PLAY operations
    - Each LOAD must complete before its corresponding PLAY starts
    - Serial LOAD constraint: LOAD operations on the same board must not overlap
    
    Args:
        events: Original list of LogicalEvent objects
        pipeline_pairs: List of identified LOAD→PLAY pairs
        
    Returns:
        List of LogicalEvent objects with optimized timestamps
    """
    if not pipeline_pairs:
        return events  # No optimization needed
    
    print("    Calculating optimal schedule for pipeline pairs...")
    
    # Create a copy of events to avoid modifying the original
    optimized_events = []
    events_to_reschedule = {}  # {original_event_id: new_timestamp}
    
    # Sort pairs by their original PLAY start time for scheduling
    sorted_pairs = sorted(pipeline_pairs, key=lambda p: p.play_start_time)
    
    # Track when LOAD operations can start (considering serial constraint)
    last_load_end_time = 0
    
    for pair in sorted_pairs:
        load_event = pair.load_event
        play_start_time = pair.play_start_time
        load_cost = pair.load_cost_cycles
        
        # Calculate the latest possible start time for the LOAD
        # (LOAD must complete before PLAY starts)
        latest_load_start = play_start_time - load_cost
        
        # Calculate the earliest possible start time for the LOAD
        # (Cannot overlap with previous LOAD operations)
        earliest_load_start = max(0, last_load_end_time)
        
        if earliest_load_start <= latest_load_start:
            # Optimization: Schedule LOAD as late as possible while meeting constraints
            optimal_load_start = latest_load_start
            events_to_reschedule[id(load_event)] = optimal_load_start
            last_load_end_time = optimal_load_start + load_cost
            
            print(f"      Optimized LOAD on {pair.channel.global_id}: {load_event.timestamp_cycles}c → {optimal_load_start}c (saved {load_event.timestamp_cycles - optimal_load_start}c)")
        else:
            # Cannot optimize: would violate serial LOAD constraint
            # Keep original timing but update last_load_end_time
            original_load_start = load_event.timestamp_cycles
            if original_load_start < last_load_end_time:
                # Need to delay this LOAD to avoid overlap
                adjusted_load_start = last_load_end_time
                events_to_reschedule[id(load_event)] = adjusted_load_start
                last_load_end_time = adjusted_load_start + load_cost
                print(f"      Delayed LOAD on {pair.channel.global_id}: {original_load_start}c → {adjusted_load_start}c (serial constraint)")
            else:
                last_load_end_time = original_load_start + load_cost
                print(f"      Kept LOAD on {pair.channel.global_id} at {original_load_start}c (no optimization possible)")
    
    # Apply rescheduling to create optimized event list
    for event in events:
        event_id = id(event)
        if event_id in events_to_reschedule:
            # Create new event with updated timestamp
            new_timestamp = events_to_reschedule[event_id]
            optimized_event = LogicalEvent(
                timestamp_cycles=new_timestamp,
                operation=event.operation,
                oasm_calls=event.oasm_calls,
                cost_cycles=event.cost_cycles
            )
            optimized_events.append(optimized_event)
        else:
            # Keep original event
            optimized_events.append(event)
    
    return optimized_events


def _pass4_generate_oasm_calls(events_by_board: Dict[OASMAddress, List[LogicalEvent]]) -> List[OASMCall]:
    """
    Pass 4: Generates the final scheduled OASM calls from the enriched
    logical events, including intelligent pipeline scheduling optimization.
    """
    print("Compiler Pass 4: Generating and scheduling OASM calls...")
    all_calls: List[OASMCall] = []

    for adr, events in events_by_board.items():
        if not events:
            continue
        
        # Step 1: Identify pipeline pairs for optimization
        pipeline_pairs = _identify_pipeline_pairs(events)
        print(f"  Board {adr.value}: Found {len(pipeline_pairs)} pipeline pairs")
        
        # Step 2: Calculate optimal scheduling for pipeline pairs
        optimized_events = _calculate_optimal_schedule(events, pipeline_pairs)
        print(f"  Board {adr.value}: Applied optimization to {len(optimized_events)} events")

        previous_ts = 0

        # Use optimized events for final scheduling
        # Sort by new timestamps and group by timestamp
        optimized_events.sort(key=lambda e: e.timestamp_cycles)
        sorted_timestamps = sorted(list(set(e.timestamp_cycles for e in optimized_events)))
        
        events_by_ts: Dict[int, List[LogicalEvent]] = {}
        for event in optimized_events:
            if event.timestamp_cycles not in events_by_ts:
                events_by_ts[event.timestamp_cycles] = []
            events_by_ts[event.timestamp_cycles].append(event)

        for i, timestamp in enumerate(sorted_timestamps):
            # Calculate wait time to next timestamp
            wait_cycles = timestamp - previous_ts
            
            if wait_cycles < 0:
                raise ValueError(f"Negative wait time calculated at timestamp {timestamp}.")
            
            if wait_cycles > 0:
                all_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.WAIT_US, args=(cycles_to_us(wait_cycles),)))
            
            # Append the pre-translated OASM calls for this timestamp
            for event in events_by_ts[timestamp]:
                all_calls.extend(event.oasm_calls)

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

def execute_oasm_calls(calls: List[OASMCall], assembler_seq=None):
    """执行 OASM 调用序列并生成实际的 RTMQ 汇编代码
    
    Args:
        calls: List of OASM calls to execute
        assembler_seq: Pre-initialized OASM assembler sequence. If None, falls back to mock execution.
    """
    print("\n--- Executing OASM Calls ---")
    if not calls:
        print("No OASM calls to execute.")
        return True, assembler_seq
    
    if assembler_seq is not None and OASM_AVAILABLE:
        print("🔧 Generating actual RTMQ assembly...")
        try:
            for i, call in enumerate(calls):
                func = OASM_FUNCTION_MAP.get(call.dsl_func)
                if func is None:
                    print(f"Error: OASM function '{call.dsl_func.name}' not found in map.")
                    return False, assembler_seq
                
                args_str = ", ".join(map(str, call.args))
                kwargs_str = ", ".join(f"{k}={v}" for k, v in call.kwargs.items()) if call.kwargs else ""
                params_str = ", ".join(filter(None, [args_str, kwargs_str]))
                print(f"[{i+1:02d}] Board '{call.adr.value}': Calling {func.__name__}({params_str})")
                
                if call.kwargs:
                    assembler_seq(call.adr.value, func, *call.args, **call.kwargs)
                else:
                    assembler_seq(call.adr.value, func, *call.args)
            
            board_names = set(call.adr.value for call in calls)
            for board_name in board_names:
                print(f"\n📋 Generated RTMQ assembly for {board_name}:")
                try:
                    if OASM_AVAILABLE:
                        asm_lines = disassembler(core=C_RWG)(assembler_seq.asm[board_name])
                        for line in asm_lines:
                            print(f"   {line}")
                    else:
                        print(f"   OASM not available for disassembly")
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
    else:
        print("⚠️  OASM modules not available or no assembler_seq provided, falling back to mock execution...")
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
            kwargs_str = ", ".join(f"{k}={v}" for k, v in call.kwargs.items()) if call.kwargs else ""
            params_str = ", ".join(filter(None, [args_str, kwargs_str]))
            print(f"[{i+1:02d}] Board '{call.adr.value}': Calling {func.__name__}({params_str})")
            
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
