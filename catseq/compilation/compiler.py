"""
OASM compiler for converting Morphism objects to OASM DSL calls.

This module provides the compilation logic for translating high-level
Morphism objects into concrete OASM DSL function calls. It uses a multi-pass
architecture to support pipelined operations and timing checks.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Callable, Union, Optional

from ..types.common import OperationType, AtomicMorphism, Channel
from ..types.timing import LogicalTimestamp, TimestampType, is_same_epoch
from ..lanes import merge_board_lanes
from ..types.rwg import RWGWaveformInstruction
from ..time_utils import cycles_to_us
from .types import OASMAddress, OASMFunction, OASMCall
from .functions import (
    ttl_config,
    ttl_set,
    wait_us,
    wait_master,
    trig_slave,
    rwg_init,
    rwg_set_carrier,
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

# --- Compiler Constants ---

# Placeholder for master wait time calculation (Plan 3)
WAIT_TIME_PLACEHOLDER = -999999

# --- Compiler Data Structures ---

@dataclass
class LogicalEvent:
    """
    Internal representation of a single logical operation on the timeline.
    This dataclass is progressively enriched by the compiler passes.
    
    Supports both legacy integer timestamps and new compound logical timestamps.
    """
    timestamp_cycles: int  # Legacy field for backward compatibility
    operation: AtomicMorphism
    
    # Populated by Pass 1 (Translation)
    oasm_calls: List[OASMCall] = field(default_factory=list)
    
    # Populated by Pass 2 (Cost Analysis)
    cost_cycles: int = 0
    
    # New compound timestamp support (optional for migration)
    logical_timestamp: LogicalTimestamp = field(default=None)
    
    def __post_init__(self):
        # Auto-generate logical timestamp from legacy timestamp if not provided
        if self.logical_timestamp is None:
            # Default epoch is 0 for backward compatibility
            self.logical_timestamp = LogicalTimestamp.from_cycles(0, self.timestamp_cycles)
    
    @property
    def effective_timestamp_cycles(self) -> int:
        """Get the effective timestamp in cycles, preferring logical timestamp."""
        return self.logical_timestamp.time_offset_cycles
    
    @property  
    def epoch(self) -> int:
        """Get the epoch of this event."""
        return self.logical_timestamp.epoch
    
    def is_same_epoch(self, other: "LogicalEvent") -> bool:
        """Check if this event is in the same epoch as another event."""
        return self.logical_timestamp.epoch == other.logical_timestamp.epoch

def _detect_epoch_boundaries(events: List[LogicalEvent]) -> List[LogicalEvent]:
    """
    Detect synchronization boundaries and assign correct epochs to events.
    
    This function scans through events and increments the epoch whenever
    a complete set of synchronization operations is detected.
    
    Args:
        events: List of LogicalEvent objects with preliminary timestamps
        
    Returns:
        List of LogicalEvent objects with correct logical timestamps including epochs
    """
    if not events:
        return events
        
    # Group events by their original timestamp to detect sync points
    events_by_timestamp: Dict[int, List[LogicalEvent]] = {}
    for event in events:
        ts = event.timestamp_cycles
        if ts not in events_by_timestamp:
            events_by_timestamp[ts] = []
        events_by_timestamp[ts].append(event)
    
    processed_events = []
    current_epoch = 0
    
    # Process events in chronological order
    for timestamp in sorted(events_by_timestamp.keys()):
        timestamp_events = events_by_timestamp[timestamp]
        
        # Check if this timestamp contains a complete synchronization set
        has_sync_master = any(e.operation.operation_type == OperationType.SYNC_MASTER 
                             for e in timestamp_events)
        has_sync_slave = any(e.operation.operation_type == OperationType.SYNC_SLAVE 
                            for e in timestamp_events)
        
        # If we have both master and slave sync operations at this timestamp,
        # this marks the end of an epoch and the beginning of the next one
        if has_sync_master and has_sync_slave:
            # Current sync operations complete this epoch
            for event in timestamp_events:
                event.logical_timestamp = LogicalTimestamp.from_cycles(current_epoch, timestamp)
                processed_events.append(event)
            
            # Increment epoch for subsequent events
            current_epoch += 1
        else:
            # Regular operations in current epoch
            for event in timestamp_events:
                event.logical_timestamp = LogicalTimestamp.from_cycles(current_epoch, timestamp)
                processed_events.append(event)
    
    return processed_events

def _check_cross_epoch_violations(events_by_board: Dict[OASMAddress, List[LogicalEvent]]) -> None:
    """
    Check for operations that would violate epoch boundaries.
    
    This function scans through all events and detects violations such as:
    1. Operations that depend on timing relationships across different epochs
    2. Pipelining constraints that span epoch boundaries
    3. Any timing calculations that would be invalid across sync points
    
    Args:
        events_by_board: Events organized by board, with logical timestamps assigned
        
    Raises:
        ValueError: If cross-epoch timing violations are detected
    """
    for board_adr, events in events_by_board.items():
        if not events:
            continue
            
        # Group events by epoch for analysis
        events_by_epoch: Dict[int, List[LogicalEvent]] = {}
        for event in events:
            epoch = event.logical_timestamp.epoch
            if epoch not in events_by_epoch:
                events_by_epoch[epoch] = []
            events_by_epoch[epoch].append(event)
        
        # No violations possible with single epoch
        if len(events_by_epoch) <= 1:
            continue
            
        print(f"  Board {board_adr.value}: Checking {len(events_by_epoch)} epochs for violations...")
        
        # Check for specific violation patterns
        _check_pipelining_across_epochs(board_adr, events_by_epoch)
        _check_timing_dependencies_across_epochs(board_adr, events)

def _check_pipelining_across_epochs(board_adr: OASMAddress, events_by_epoch: Dict[int, List[LogicalEvent]]) -> None:
    """
    Check for pipelining operations that span across epoch boundaries.
    
    Pipelining (like RWG load operations scheduled during previous play operations)
    cannot work across epochs because the time reference system changes.
    """
    epochs = sorted(events_by_epoch.keys())
    
    for i in range(len(epochs) - 1):
        current_epoch = epochs[i]
        next_epoch = epochs[i + 1]
        
        current_events = events_by_epoch[current_epoch]
        next_events = events_by_epoch[next_epoch]
        
        # Look for operations in next epoch that might depend on timing from current epoch
        for next_event in next_events:
            if next_event.operation.operation_type == OperationType.RWG_LOAD_COEFFS:
                # Check if this load operation was scheduled based on previous epoch timing
                # This is detected by checking if the load happens very early in the new epoch
                # (which would suggest it was scheduled during previous epoch's play operation)
                if next_event.logical_timestamp.time_offset_cycles < 100:  # Less than 100 cycles = likely pipelined
                    raise ValueError(
                        f"Cross-epoch pipelining violation detected on board {board_adr.value}: "
                        f"RWG_LOAD_COEFFS operation at epoch {next_epoch}, offset {next_event.logical_timestamp.time_offset_cycles} cycles "
                        f"appears to be pipelined from previous epoch {current_epoch}. "
                        f"Pipelining across synchronization boundaries is not allowed as it violates "
                        f"the time reference system boundaries."
                    )

def _check_timing_dependencies_across_epochs(board_adr: OASMAddress, events: List[LogicalEvent]) -> None:
    """
    Check for operations that have timing dependencies spanning epochs.
    
    This includes operations that were scheduled based on timing calculations
    that would be invalid across epoch boundaries.
    """
    # Sort events by their original timestamp_cycles to detect potential cross-epoch dependencies
    events_by_original_time = {}
    for event in events:
        orig_time = event.timestamp_cycles
        if orig_time not in events_by_original_time:
            events_by_original_time[orig_time] = []
        events_by_original_time[orig_time].append(event)
    
    # Look for events that have the same original timestamp but different epochs
    # This could indicate a timing dependency that spans epochs
    for orig_time, time_events in events_by_original_time.items():
        if len(time_events) > 1:
            epochs_at_time = set(event.logical_timestamp.epoch for event in time_events)
            if len(epochs_at_time) > 1:
                # Events with same original timing but different epochs - potential violation
                epoch_list = sorted(epochs_at_time)
                event_types = [event.operation.operation_type.name for event in time_events]
                
                # This is actually expected for synchronization operations themselves
                if any(op_type in ['SYNC_MASTER', 'SYNC_SLAVE'] for op_type in event_types):
                    continue  # Sync operations are expected to span epoch boundaries
                    
                raise ValueError(
                    f"Cross-epoch timing dependency detected on board {board_adr.value}: "
                    f"Operations {event_types} were scheduled for the same original time {orig_time} cycles "
                    f"but span across epochs {epoch_list}. This suggests a timing calculation that "
                    f"illegally crosses synchronization boundaries."
                )

# --- Plan 3 Refactored Passes ---

def _pass1_extract_and_translate(morphism) -> Dict[OASMAddress, List[LogicalEvent]]:
    """Pass 1: Extract events from morphism and translate to OASM calls (Plan 3)"""
    print("Compiler Pass 1: Extracting events and translating to OASM calls...")
    
    # Step 1: Extract events from morphism (original Pass 0 logic)
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
            # Identity operations are purely for timing shifts during morphism
            # composition. They do not translate to physical events.
            if pop.operation.operation_type == OperationType.IDENTITY:
                continue

            event = LogicalEvent(
                timestamp_cycles=pop.timestamp_cycles,
                operation=pop.operation
            )
            events_by_board[adr].append(event)
    
    for adr in events_by_board:
        events_by_board[adr].sort(key=lambda e: e.timestamp_cycles)
    
    # Step 2: Translate events to OASM calls (original Pass 1 logic with placeholder mechanism)
    print("  Translating logical events to OASM calls...")
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
                        # Board-level initialization - no OASM call generated here
                        # This is handled in the merged section below
                        pass
                    
                    case OperationType.RWG_SET_CARRIER:
                        # Channel-level carrier frequency setting
                        event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.RWG_SET_CARRIER, args=(op.channel.local_id, op.end_state.carrier_freq)))
                    
                    case OperationType.RWG_RF_SWITCH:
                        ch_mask = (1 << op.channel.local_id)
                        # state_mask: 0 = RF enabled, 1 = RF disabled.
                        state_mask = 0 if op.end_state.rf_on else ch_mask
                        event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.RWG_RF_SWITCH, args=(ch_mask, state_mask)))

                    case OperationType.SYNC_MASTER:
                        # Master synchronization: Use placeholder for wait time (Plan 3)
                        sync_code = 12345  # Compiler-generated sync code
                        event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.TRIG_SLAVE, args=(WAIT_TIME_PLACEHOLDER, sync_code)))
                    
                    case OperationType.SYNC_SLAVE:
                        # This is now handled as a merged operation to avoid multiple wait_master calls
                        pass

                    case OperationType.RWG_LOAD_COEFFS:
                        # Generate separate OASM calls for each WaveformParams in the instruction
                        # The OASM DSL function expects individual WaveformParams, not the entire instruction
                        if isinstance(op.end_state, RWGWaveformInstruction):
                            for waveform_params in op.end_state.params:
                                event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.RWG_LOAD_WAVEFORM, args=(waveform_params,)))
                    
                    case _:
                        # This operation is either a merged operation or doesn't translate to a call.
                        pass

            # Handle many-to-1 (merged) translations and board-level operations
            
            # Handle RWG board-level initialization (only once per board per timestamp)
            if OperationType.RWG_INIT in ops_by_type:
                # Add board-level RWG_INIT only once per timestamp
                for event in ts_events:
                    if event.operation.operation_type == OperationType.RWG_INIT:
                        # Check if we already added board init for this timestamp
                        board_init_added = any(
                            call.dsl_func == OASMFunction.RWG_INIT 
                            for other_event in ts_events 
                            for call in other_event.oasm_calls
                        )
                        if not board_init_added:
                            # Add board-level init to the first RWG_INIT event at this timestamp
                            event.oasm_calls.insert(0, OASMCall(adr=adr, dsl_func=OASMFunction.RWG_INIT, args=()))
                        break

            if OperationType.SYNC_SLAVE in ops_by_type:
                # Find the first SYNC_SLAVE event to attach the single WAIT_MASTER call to.
                for event in ts_events:
                    if event.operation.operation_type == OperationType.SYNC_SLAVE:
                        # This check is implicit: we only add it once and then break.
                        sync_code = 12345  # Same sync code as master
                        event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.WAIT_MASTER, args=(sync_code,)))
                        break # Ensure only one WAIT_MASTER is added per board per timestamp
            
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

    return events_by_board

def _pass2_cost_and_epoch_analysis(events_by_board: Dict[OASMAddress, List[LogicalEvent]], assembler_seq=None):
    """Pass 2: Cost analysis and epoch detection (Plan 3)"""
    print("Compiler Pass 2: Cost analysis and epoch detection...")
    
    # Step 1: Detect epoch boundaries GLOBALLY and assign logical timestamps
    print("  Detecting epoch boundaries and assigning logical timestamps...")
    
    # Create a flat list of all events from all boards for global epoch detection
    all_events = [event for events in events_by_board.values() for event in events]
    
    # The _detect_epoch_boundaries function will modify the events in place,
    # which are shared with the original events_by_board dictionary.
    _detect_epoch_boundaries(all_events)

    # Print summary of epochs found on each board
    for adr, events in events_by_board.items():
        epoch_info = {}
        for event in events:
            epoch = event.epoch
            if epoch not in epoch_info:
                epoch_info[epoch] = 0
            epoch_info[epoch] += 1
        if len(epoch_info) > 1:
            print(f"    Board {adr.value}: Found {len(epoch_info)} epochs: {dict(sorted(epoch_info.items()))}")
        else:
            print(f"    Board {adr.value}: Single epoch with {sum(epoch_info.values())} events")

    # Step 2: Analyze costs for all operations (original Pass 2 logic)
    print("  Analyzing costs for all operations via assembly generation...")
    
    if assembler_seq is None:
        if OASM_AVAILABLE:
            print("    Warning: No assembler provided. Cost analysis will be skipped.")
        else:
            print("    Warning: OASM modules not available. Skipping cost analysis.")
        return

    for adr, events in events_by_board.items():
        print(f"    Analyzing costs for board {adr.value}...")
        for event in events:
            # Analyze cost for all operations that have OASM calls
            if event.oasm_calls:
                event.cost_cycles = _analyze_operation_cost(event, adr, assembler_seq)
                print(f"      - {event.operation.operation_type.name} at t={event.timestamp_cycles}: {event.cost_cycles} cycles")
            else:
                event.cost_cycles = 0
                print(f"      - {event.operation.operation_type.name} at t={event.timestamp_cycles}: 0 cycles (no OASM calls)")

# --- Main Compiler Entry Point ---

def compile_to_oasm_calls(morphism, assembler_seq=None, _return_internal_events=False) -> Union[Dict[OASMAddress, List[OASMCall]], Dict[OASMAddress, List[LogicalEvent]]]:
    """Drives the Plan 3 five-pass compilation process.
    
    Args:
        morphism: The morphism to compile
        assembler_seq: Pre-initialized OASM assembler sequence for cost analysis.
                      If None, cost analysis will be skipped when OASM is not available.
        _return_internal_events: For testing, return internal events instead of calls
    """
    
    # Pass 1: Extract events from morphism and translate to OASM calls (Plan 3)
    events_by_board = _pass1_extract_and_translate(morphism)
    
    # Pass 2: Cost analysis and epoch detection (Plan 3)
    _pass2_cost_and_epoch_analysis(events_by_board, assembler_seq)
    
    # Pass 3: Schedule & Optimize (Plan 3 implementation)
    _pass3_schedule_and_optimize(events_by_board)
    
    # Pass 4: Constraint Validation (Plan 3 - pure validation after scheduling)
    _pass4_validate_constraints(events_by_board)

    # For testing purposes, allow returning the internal event list
    if _return_internal_events:
        return events_by_board
    
    # Pass 5: Final Code Generation (Plan 3)
    oasm_calls = _pass5_generate_final_calls(events_by_board)
    
    return oasm_calls

def _pass5_generate_final_calls(events_by_board: Dict[OASMAddress, List[LogicalEvent]]) -> Dict[OASMAddress, List[OASMCall]]:
    """
    Pass 5: Final Code Generation (Plan 3)
    
    完成最终代码生成：
    1. 计算最终master wait time
    2. 替换所有WAIT_TIME_PLACEHOLDER  
    3. 生成最终OASMCall序列
    """
    print("Compiler Pass 5: Final code generation with placeholder replacement (Plan 3)...")
    
    # Step 1: 替换WAIT_TIME_PLACEHOLDER
    _replace_wait_time_placeholders(events_by_board)
    
    # Step 2: 生成最终OASM调用序列（重用现有实现）
    print("  Generating final OASM call sequence...")
    oasm_calls = _pass4_generate_oasm_calls(events_by_board)
    
    return oasm_calls

def _replace_wait_time_placeholders(events_by_board: Dict[OASMAddress, List[LogicalEvent]]):
    """
    Pass 5 Preview: Replace WAIT_TIME_PLACEHOLDER with calculated master wait times.
    
    This implements the basic logic from Plan 3 Pass 5:
    - Calculate the maximum end time of all operations in epoch=0
    - Replace TRIG_SLAVE placeholders with the calculated wait time
    """
    print("Compiler Pass 5 Preview: Replacing WAIT_TIME_PLACEHOLDER with calculated wait times...")
    
    # Step 1: Calculate maximum end time across all boards
    max_end_time = 0
    for adr, events in events_by_board.items():
        for event in events:
            # Include both timestamp and cost for operations that have duration
            event_end_time = event.timestamp_cycles + (event.cost_cycles if event.cost_cycles else 0)
            max_end_time = max(max_end_time, event_end_time)
    
    # Add safety margin (100 cycles as used in original implementation)
    master_wait_time = max_end_time + 100
    
    # Step 2: Replace placeholders in all TRIG_SLAVE calls
    for adr, events in events_by_board.items():
        for event in events:
            # Find and replace TRIG_SLAVE calls with placeholders
            new_calls = []
            for call in event.oasm_calls:
                if (call.dsl_func == OASMFunction.TRIG_SLAVE and 
                    len(call.args) >= 2 and 
                    call.args[0] == WAIT_TIME_PLACEHOLDER):
                    # Create new call with calculated wait time
                    new_call = OASMCall(
                        adr=call.adr, 
                        dsl_func=call.dsl_func,
                        args=(master_wait_time, call.args[1]),  # Replace placeholder, keep sync_code
                        kwargs=call.kwargs
                    )
                    new_calls.append(new_call)
                    print(f"    Replaced placeholder in {adr.value} with wait time: {master_wait_time} cycles")
                else:
                    new_calls.append(call)
            event.oasm_calls = new_calls

def _pass3_schedule_and_optimize(events_by_board: Dict[OASMAddress, List[LogicalEvent]]):
    """
    Pass 3: Schedule & Optimize - Pipelining scheduler (New Plan)
    
    This pass implements the core pipelining optimization. It identifies LOAD-PLAY
    pairs and schedules the LOAD operation as late as possible before the PLAY
    operation, utilizing idle time.
    """
    print("Compiler Pass 3: Scheduling with pipelining optimization...")
    
    for adr, events in events_by_board.items():
        # 1. 识别LOAD和PLAY操作
        # Note: _identify_pipeline_pairs is now used here for the main scheduling logic
        pipeline_pairs = _identify_pipeline_pairs(events)
        if not pipeline_pairs:
            continue
            
        print(f"  Board {adr.value}: Found {len(pipeline_pairs)} pipeline pairs for optimization")
        
        # 2. 计算最优调度方案
        # This is the correct scheduling logic as per user's design intent
        optimized_events = _calculate_optimal_schedule(events, pipeline_pairs)
        
        # 3. 更新事件列表
        events_by_board[adr] = optimized_events
        print(f"    Completed pipelining optimization for board {adr.value}")

def _identify_load_play_pairs(load_events: List[LogicalEvent], play_events: List[LogicalEvent]) -> List[Dict]:
    """识别LOAD-PLAY对应关系"""
    pairs = []
    
    for load_event in load_events:
        # 找到同一通道上的下一个PLAY操作
        load_channel = load_event.operation.channel
        load_time = load_event.timestamp_cycles
        
        corresponding_play = None
        min_time_diff = float('inf')
        
        for play_event in play_events:
            if (play_event.operation.channel == load_channel and 
                play_event.timestamp_cycles >= load_time):
                time_diff = play_event.timestamp_cycles - load_time
                if time_diff < min_time_diff:
                    min_time_diff = time_diff
                    corresponding_play = play_event
        
        if corresponding_play:
            pairs.append({
                'load_event': load_event,
                'play_event': corresponding_play,
                'channel': load_channel
            })
    
    return pairs

def _schedule_loads_serially(events: List[LogicalEvent], 
                           sorted_loads: List[LogicalEvent], 
                           load_deadlines: Dict[LogicalEvent, int],
                           play_events: List[LogicalEvent]) -> List[LogicalEvent]:
    """串行调度LOAD操作，利用时间窗口优化"""
    
    if not sorted_loads:
        return events
    
    print(f"      Scheduling {len(sorted_loads)} LOAD operations serially...")
    
    # 创建事件的副本以便修改
    optimized_events = events.copy()
    current_load_end_time = 0
    
    for i, load_event in enumerate(sorted_loads):
        deadline = load_deadlines[id(load_event)]  # 使用id()作为key
        load_duration = load_event.cost_cycles if load_event.cost_cycles else 0
        
        print(f"        LOAD {i+1}: duration={load_duration}c, deadline={deadline}c")
        
        # 策略1：尝试在当前时间调度
        if current_load_end_time + load_duration <= deadline:
            # 可以在deadline前完成
            new_timestamp = current_load_end_time
            current_load_end_time += load_duration
            print(f"          → Scheduled at {new_timestamp}c (serial execution)")
        else:
            # 策略2：寻找播放期间的时间窗口
            available_window = _find_available_play_window(
                current_load_end_time, load_duration, deadline, play_events
            )
            
            if available_window:
                new_timestamp = available_window['start']
                current_load_end_time = new_timestamp + load_duration
                print(f"          → Scheduled at {new_timestamp}c (using play window)")
            else:
                # 无法优化，保持原时间戳但记录警告
                new_timestamp = load_event.timestamp_cycles
                current_load_end_time = max(current_load_end_time, new_timestamp + load_duration)
                print(f"          → Kept original time {new_timestamp}c (no optimization possible)")
        
        # 更新事件的时间戳
        for event in optimized_events:
            if event is load_event:
                event.timestamp_cycles = new_timestamp
                break
    
    return optimized_events

def _find_available_play_window(current_time: int, required_duration: int, 
                               deadline: int, play_events: List[LogicalEvent]) -> Optional[Dict]:
    """在其他通道的播放期间寻找可用时间窗口"""
    
    for play_event in play_events:
        play_start = play_event.timestamp_cycles
        play_duration = play_event.operation.duration_cycles if play_event.operation.duration_cycles else 0
        play_end = play_start + play_duration
        
        # 检查播放期间是否有足够时间
        if (play_start >= current_time and 
            play_start + required_duration <= min(play_end, deadline)):
            return {'start': play_start, 'duration': required_duration}
        
        # 检查播放期间的剩余时间
        if (play_start < current_time < play_end and
            current_time + required_duration <= min(play_end, deadline)):
            return {'start': current_time, 'duration': required_duration}
    
    return None

def _pass4_validate_constraints(events_by_board: Dict[OASMAddress, List[LogicalEvent]]):
    """
    Pass 4: Constraint Validation (Plan 3)
    
    纯验证Pass，检查调度后的结果：
    1. 验证串行约束满足 - 确保同板卡LOAD操作确实被串行调度
    2. 验证deadline满足 - 每个LOAD都在对应PLAY前完成  
    3. 验证时序一致性 - 无负等待时间，时间线连续
    4. 验证跨epoch边界 - 调度优化没有违反epoch语义
    """
    print("Compiler Pass 4: Validating constraints after scheduling (Plan 3)...")
    
    for adr, events in events_by_board.items():
        print(f"  Validating board {adr.value}...")
        
        # 1. 验证串行约束
        _validate_serial_load_constraints(adr, events)
        
        # 2. 验证LOAD deadline满足
        _validate_load_deadlines(adr, events)
        
        # 3. 验证时序一致性
        _validate_timing_consistency(adr, events)
        
        # 4. 验证跨epoch边界（重用现有实现）
        _check_cross_epoch_violations_single_board(adr, events)
        
        print(f"    ✓ All constraints validated for board {adr.value}")

def _validate_serial_load_constraints(adr, events: List[LogicalEvent]):
    """验证LOAD操作确实被串行调度"""
    load_events = [e for e in events if e.operation.operation_type == OperationType.RWG_LOAD_COEFFS]
    
    if len(load_events) <= 1:
        return  # 单个或无LOAD操作无需验证
    
    # 按时间戳排序
    sorted_loads = sorted(load_events, key=lambda x: x.timestamp_cycles)
    
    for i in range(len(sorted_loads) - 1):
        current_load = sorted_loads[i]
        next_load = sorted_loads[i + 1]
        
        current_end = current_load.timestamp_cycles + (current_load.cost_cycles or 0)
        next_start = next_load.timestamp_cycles
        
        if next_start < current_end:
            raise ValueError(
                f"Serial constraint violation on board {adr.value}: "
                f"LOAD operations overlap - load1 ends at {current_end}c, load2 starts at {next_start}c"
            )
    
    print(f"    ✓ Serial LOAD constraints satisfied ({len(load_events)} operations)")

def _validate_load_deadlines(adr, events: List[LogicalEvent]):
    """验证每个LOAD都在对应PLAY的deadline前完成"""
    load_events = [e for e in events if e.operation.operation_type == OperationType.RWG_LOAD_COEFFS]
    play_events = [e for e in events if e.operation.operation_type == OperationType.RWG_UPDATE_PARAMS]
    
    if not load_events or not play_events:
        return
    
    # 重用LOAD-PLAY配对逻辑
    load_play_pairs = _identify_load_play_pairs(load_events, play_events)
    
    for pair in load_play_pairs:
        load_event = pair['load_event']
        play_event = pair['play_event']
        
        load_end = load_event.timestamp_cycles + (load_event.cost_cycles or 0)
        play_start = play_event.timestamp_cycles
        
        if load_end > play_start:
            raise ValueError(
                f"Deadline violation on board {adr.value}: "
                f"LOAD operation ends at {load_end}c but PLAY starts at {play_start}c"
            )
    
    print(f"    ✓ LOAD deadlines satisfied ({len(load_play_pairs)} pairs)")

def _validate_timing_consistency(adr, events: List[LogicalEvent]):
    """验证时序一致性 - 无负等待时间，时间线连续"""
    if not events:
        return
    
    # 检查是否有负时间戳
    for event in events:
        if event.timestamp_cycles < 0:
            raise ValueError(
                f"Timing consistency violation on board {adr.value}: "
                f"Event has negative timestamp: {event.timestamp_cycles}c"
            )
    
    # 检查是否有明显不合理的时间跳跃
    sorted_events = sorted(events, key=lambda x: x.timestamp_cycles)
    prev_time = 0
    
    for event in sorted_events:
        if event.timestamp_cycles < prev_time:
            raise ValueError(
                f"Timing consistency violation on board {adr.value}: "
                f"Events are not properly ordered in time"
            )
        prev_time = event.timestamp_cycles
    
    print(f"    ✓ Timing consistency validated ({len(events)} events)")

def _check_cross_epoch_violations_single_board(adr, events: List[LogicalEvent]):
    """验证跨epoch边界 - 单板卡版本"""
    # 按epoch分组
    events_by_epoch = {}
    for event in events:
        epoch = getattr(event.logical_timestamp, 'epoch', 0) if hasattr(event, 'logical_timestamp') else 0
        if epoch not in events_by_epoch:
            events_by_epoch[epoch] = []
        events_by_epoch[epoch].append(event)
    
    if len(events_by_epoch) <= 1:
        return  # 单个或无epoch无需验证
    
    # 检查跨epoch的潜在问题
    epochs = sorted(events_by_epoch.keys())
    for i in range(len(epochs) - 1):
        current_epoch = epochs[i]
        next_epoch = epochs[i + 1]
        
        current_events = events_by_epoch[current_epoch]
        next_events = events_by_epoch[next_epoch]
        
        # 检查下一个epoch的早期LOAD操作（可能违反时间参考系统）
        for next_event in next_events:
            if next_event.operation.operation_type == OperationType.RWG_LOAD_COEFFS:
                if hasattr(next_event, 'logical_timestamp') and next_event.logical_timestamp.time_offset_cycles < 100:
                    raise ValueError(
                        f"Cross-epoch violation on board {adr.value}: "
                        f"LOAD operation at epoch {next_epoch} appears to be pipelined from epoch {current_epoch}"
                    )
    
    print(f"    ✓ Cross-epoch boundaries validated ({len(epochs)} epochs)")

# --- Compiler Passes ---

def _pass0_extract_events(morphism) -> Dict[OASMAddress, List[LogicalEvent]]:
    """DEPRECATED: Pass 0: Flattens the morphism into a time-sorted list of LogicalEvents per board.
    
    This function is deprecated. Use _pass1_extract_and_translate instead which merges Pass 0+1.
    """
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
            # Identity operations are purely for timing shifts during morphism
            # composition. They do not translate to physical events.
            if pop.operation.operation_type == OperationType.IDENTITY:
                continue

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
    """DEPRECATED: Pass 1: Translates the abstract intent of each LogicalEvent into a list
    of concrete OASMCall objects, stored within the event itself.
    
    This function is deprecated. Use _pass1_extract_and_translate instead which merges Pass 0+1.
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
                        # Board-level initialization - no OASM call generated here
                        # This is handled in the merged section below
                        pass
                    
                    case OperationType.RWG_SET_CARRIER:
                        # Channel-level carrier frequency setting
                        event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.RWG_SET_CARRIER, args=(op.channel.local_id, op.end_state.carrier_freq)))
                    
                    case OperationType.RWG_RF_SWITCH:
                        ch_mask = (1 << op.channel.local_id)
                        # state_mask: 0 = RF enabled, 1 = RF disabled.
                        state_mask = 0 if op.end_state.rf_on else ch_mask
                        event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.RWG_RF_SWITCH, args=(ch_mask, state_mask)))

                    case OperationType.SYNC_MASTER:
                        # Master synchronization: trigger all slaves after waiting
                        sync_code = 12345  # Compiler-generated sync code
                        wait_time_cycles = _calculate_master_wait_time(events_by_board, event.timestamp_cycles)
                        event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.TRIG_SLAVE, args=(wait_time_cycles, sync_code)))
                    
                    case OperationType.SYNC_SLAVE:
                        # This is now handled as a merged operation to avoid multiple wait_master calls
                        pass

                    case OperationType.RWG_LOAD_COEFFS:
                        # Generate separate OASM calls for each WaveformParams in the instruction
                        # The OASM DSL function expects individual WaveformParams, not the entire instruction
                        if isinstance(op.end_state, RWGWaveformInstruction):
                            for waveform_params in op.end_state.params:
                                event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.RWG_LOAD_WAVEFORM, args=(waveform_params,)))
                    
                    case _:
                        # This operation is either a merged operation or doesn't translate to a call.
                        pass

            # Handle many-to-1 (merged) translations and board-level operations
            
            # Handle RWG board-level initialization (only once per board per timestamp)
            if OperationType.RWG_INIT in ops_by_type:
                # Add board-level RWG_INIT only once per timestamp
                for event in ts_events:
                    if event.operation.operation_type == OperationType.RWG_INIT:
                        # Check if we already added board init for this timestamp
                        board_init_added = any(
                            call.dsl_func == OASMFunction.RWG_INIT 
                            for other_event in ts_events 
                            for call in other_event.oasm_calls
                        )
                        if not board_init_added:
                            # Add board-level init to the first RWG_INIT event at this timestamp
                            event.oasm_calls.insert(0, OASMCall(adr=adr, dsl_func=OASMFunction.RWG_INIT, args=()))
                        break

            if OperationType.SYNC_SLAVE in ops_by_type:
                # Find the first SYNC_SLAVE event to attach the single WAIT_MASTER call to.
                for event in ts_events:
                    if event.operation.operation_type == OperationType.SYNC_SLAVE:
                        # This check is implicit: we only add it once and then break.
                        sync_code = 12345  # Same sync code as master
                        event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.WAIT_MASTER, args=(sync_code,)))
                        break # Ensure only one WAIT_MASTER is added per board per timestamp
            
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
    """DEPRECATED: Pass 2: Analyzes execution cost for all operations by generating and analyzing
    OASM assembly code. This provides precise timing for global synchronization.
    
    This function is deprecated. Use _pass2_cost_and_epoch_analysis instead which merges Pass 1.5+2.
    
    Args:
        events_by_board: Events organized by board
        assembler_seq: Pre-initialized OASM assembler sequence. If None, cost analysis is skipped.
    """
    print("Compiler Pass 2: Analyzing costs for all operations via assembly generation...")
    
    if assembler_seq is None:
        if OASM_AVAILABLE:
            print("Warning: No assembler provided. Cost analysis will be skipped.")
        else:
            print("Warning: OASM modules not available. Skipping cost analysis.")
        return

    for adr, events in events_by_board.items():
        print(f"  Analyzing costs for board {adr.value}...")
        for event in events:
            # Analyze cost for all operations that have OASM calls
            if event.oasm_calls:
                event.cost_cycles = _analyze_operation_cost(event, adr, assembler_seq)
                print(f"    - {event.operation.operation_type.name} at t={event.timestamp_cycles}: {event.cost_cycles} cycles")
            else:
                event.cost_cycles = 0
                print(f"    - {event.operation.operation_type.name} at t={event.timestamp_cycles}: 0 cycles (no OASM calls)")

def _analyze_operation_cost(event: LogicalEvent, adr: OASMAddress, assembler_seq) -> int:
    """
    Analyze the execution cost of a single operation by generating and analyzing
    its OASM assembly code.
    
    Args:
        event: The logical event to analyze
        adr: Board address for assembly generation
        assembler_seq: OASM assembler sequence
        
    Returns:
        Cost in cycles, or 0 if analysis fails
    """
    try:
        # Clear assembler state for clean cost analysis
        assembler_seq.clear()
        
        # Execute all OASM calls for this operation
        for call in event.oasm_calls:
            func = OASM_FUNCTION_MAP.get(call.dsl_func)
            if func:
                if call.kwargs:
                    assembler_seq(call.adr.value, func, *call.args, **call.kwargs)
                else:
                    assembler_seq(call.adr.value, func, *call.args)

        # Check if assembly was generated
        if adr.value in assembler_seq.asm.multi:
            binary_asm = assembler_seq.asm[adr.value]
            asm_lines = disassembler(core=C_RWG)(binary_asm)
            
            cost = _estimate_oasm_cost(asm_lines)
            return cost
        else:
            return 0
            
    except Exception as e:
        print(f"      Warning: Cost analysis failed for {event.operation.operation_type.name}: {e}")
        return 0

def _calculate_pre_sync_duration_up_to(board_events: List[LogicalEvent], sync_timestamp: int) -> int:
    """
    Calculate the total execution time for operations that occur at or before the sync timestamp.
    This is used to determine how long the master board should wait before synchronization.
    
    Args:
        board_events: List of logical events for a single board
        sync_timestamp: The timestamp at which synchronization occurs
        
    Returns:
        Total duration in cycles for all pre-sync operations
    """
    # Find the completion time of the latest event that starts at or before sync_timestamp
    max_pre_sync_time = 0
    for event in board_events:
        if event.timestamp_cycles <= sync_timestamp:
            # This event is part of the pre-sync sequence, include its completion time
            event_end_time = event.timestamp_cycles + event.operation.duration_cycles
            max_pre_sync_time = max(max_pre_sync_time, event_end_time)
    
    return max_pre_sync_time

def _calculate_pre_sync_duration(board_events: List[LogicalEvent]) -> int:
    """
    Calculate the total execution time for operations that occur before global sync (t=0).
    This is used to determine how long the master board should wait before synchronization.
    
    Args:
        board_events: List of logical events for a single board
        
    Returns:
        Total duration in cycles for all pre-sync operations
    """
    pre_sync_cost = 0
    
    for event in board_events:
        if event.timestamp_cycles == 0:  # Pre-sync operations occur at t=0
            pre_sync_cost += event.cost_cycles
    
    return pre_sync_cost

def _calculate_master_wait_time(events_by_board: Dict[OASMAddress, List[LogicalEvent]], sync_timestamp: int) -> int:
    """
    Calculate the time the master board should wait before triggering global sync.
    This is based on the maximum pre-sync duration across all slave boards.
    
    Args:
        events_by_board: Events organized by board
        
    Returns:
        Wait time in cycles for master board
    """
    max_slave_duration = 0
    
    print("  Calculating master wait time based on slave board pre-sync operations...")
    
    for adr, events in events_by_board.items():
        if adr != OASMAddress.MAIN:  # Only consider slave boards
            # --- DEBUGGING START ---
            print(f"--- Events for slave board {adr.value} before duration calculation (sync_ts={sync_timestamp}): ---")
            for i, event in enumerate(events):
                if event.timestamp_cycles <= sync_timestamp:
                    print(f"  - Event {i}: ts={event.timestamp_cycles}, op={event.operation.operation_type.name}, dur={event.operation.duration_cycles}")
            print("--- End of event list ---")
            # --- DEBUGGING END ---
            slave_duration = _calculate_pre_sync_duration_up_to(events, sync_timestamp)
            max_slave_duration = max(max_slave_duration, slave_duration)
            print(f"    Slave {adr.value} pre-sync duration: {slave_duration} cycles")
    
    # Add safety margin for communication delays and timing uncertainties
    safety_margin = 100  # cycles, configurable
    total_wait = max_slave_duration + safety_margin
    
    print(f"    Master wait time: {max_slave_duration} + {safety_margin} = {total_wait} cycles")
    
    return total_wait

def _pass3_check_constraints(events_by_board: Dict[OASMAddress, List[LogicalEvent]]):
    """Pass 3: Checks for timing violations, including pipelining and global sync constraints."""
    print("Compiler Pass 3: Checking constraints...")
    
    # Check RWG_INIT global sync constraints for multi-board scenarios
    if len(events_by_board) > 1:
        print("  Multi-board scenario: Checking RWG_INIT global sync constraints...")
        for adr, events in events_by_board.items():
            for event in events:
                if event.operation.operation_type == OperationType.RWG_INIT:
                    # In a multi-board context, RWG_INIT must occur within epoch 0.
                    if event.logical_timestamp.epoch != 0:
                        raise ValueError(
                            f"Multi-board constraint violation: RWG_INIT operation on board {adr.value} "
                            f"found in epoch {event.logical_timestamp.epoch}. "
                            f"RWG_INIT is only permitted before the first global sync (in epoch=0)."
                        )
                    else:
                        print(f"    ✓ RWG_INIT on {adr.value} in epoch 0: OK")
    
    # Check pipelining constraints per board  
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
    Calculate optimal scheduling for pipeline pairs with conflict avoidance.
    
    This function implements pipelining by scheduling LOAD operations backwards
    from their corresponding PLAY operations. It is aware of ALL other operations
    on the board and will adjust the LOAD timing to avoid conflicts, ensuring
    that user-specified timestamps for visible effects are never violated.
    
    Args:
        events: Original list of all LogicalEvent objects for the board.
        pipeline_pairs: List of identified LOAD→PLAY pairs to be scheduled.
        
    Returns:
        A new list of LogicalEvent objects with optimized timestamps.
    """
    if not pipeline_pairs:
        return events

    print("    Calculating optimal schedule for pipeline pairs (with conflict avoidance)...")

    # Create a dictionary for quick access to the events that will be rescheduled.
    # The value will be the new timestamp.
    events_to_reschedule: Dict[int, int] = {id(p.load_event): 0 for p in pipeline_pairs}
    
    # Sort pairs by PLAY start time, DESCENDING, to schedule later operations first.
    sorted_pairs = sorted(pipeline_pairs, key=lambda p: (p.play_start_time, p.channel.global_id), reverse=True)

    # This tracks the start time of the previously scheduled LOAD.
    # Since we are scheduling backwards, this is the time the *next* load must finish by.
    next_load_available_ts = float('inf')

    for pair in sorted_pairs:
        load_event = pair.load_event
        play_start_time = pair.play_start_time
        load_cost = pair.load_cost_cycles

        # The latest possible time the load can finish.
        # It must finish before its own PLAY starts, and before the next LOAD (for a later PLAY) starts.
        latest_finish_by = min(play_start_time, next_load_available_ts)
        
        # The ideal start time if there are no other operations in the way.
        proposed_start_ts = latest_finish_by - load_cost
        
        # --- Conflict Detection ---
        # Find any operations that conflict with our proposed time slot.
        # A conflict occurs if another operation's time span overlaps with
        # [proposed_start_ts, proposed_start_ts + load_cost].
        
        conflicting_events = []
        for other_event in events:
            # Don't check for conflicts with the load itself or its corresponding play.
            if id(other_event) == id(load_event) or id(other_event) == id(pair.play_event):
                continue
            
            # Ignore other LOAD events that are also being rescheduled.
            if id(other_event) in events_to_reschedule:
                continue

            other_start = other_event.timestamp_cycles
            other_end = other_start + (other_event.cost_cycles or 0)
            
            # Overlap check: (StartA <= EndB) and (EndA >= StartB)
            if (proposed_start_ts < other_end) and ((proposed_start_ts + load_cost) > other_start):
                conflicting_events.append(other_event)

        # If there are conflicts, we must adjust our schedule.
        if conflicting_events:
            # Find the latest start time among all conflicting events.
            # Our load must finish before the earliest of these conflicts begins.
            earliest_conflict_start = min(e.timestamp_cycles for e in conflicting_events)
            finish_by = earliest_conflict_start
        else:
            finish_by = latest_finish_by

        # Final calculation of the new timestamp.
        new_load_ts = finish_by - load_cost
        
        events_to_reschedule[id(load_event)] = new_load_ts
        
        # The next load we schedule (which happens earlier in time) must finish before this one starts.
        next_load_available_ts = new_load_ts

        print(f"      Scheduling LOAD on {pair.channel.global_id}: {load_event.timestamp_cycles}c → {new_load_ts}c")

    # Apply rescheduling to create a new list of events
    optimized_events = []
    for event in events:
        event_id = id(event)
        if event_id in events_to_reschedule:
            new_timestamp = events_to_reschedule[event_id]
            # Create a new event with the updated timestamp
            optimized_event = LogicalEvent(
                timestamp_cycles=new_timestamp,
                operation=event.operation,
                oasm_calls=event.oasm_calls,
                cost_cycles=event.cost_cycles,
                logical_timestamp=LogicalTimestamp.from_cycles(event.epoch, new_timestamp)
            )
            optimized_events.append(optimized_event)
        else:
            # Keep original event
            optimized_events.append(event)
            
    return optimized_events


def _pass4_generate_oasm_calls(events_by_board: Dict[OASMAddress, List[LogicalEvent]]) -> Dict[OASMAddress, List[OASMCall]]:
    """
    Pass 4: Generates the final scheduled OASM calls from the enriched
    logical events, including intelligent pipeline scheduling optimization.
    """
    print("Compiler Pass 4: Generating and scheduling OASM calls...")
    calls_by_board: Dict[OASMAddress, List[OASMCall]] = {}
    
    # User-managed synchronization: sync operations are explicitly added by user via global_sync()
    board_addresses = list(events_by_board.keys())
    print(f"  Processing {len(board_addresses)} board(s): {[adr.value for adr in board_addresses]}")

    for adr, events in events_by_board.items():
        # Initialize the board's call list
        board_calls: List[OASMCall] = []
        
        if not events:
            calls_by_board[adr] = board_calls
            continue
        
        # Pass 3 has already performed the optimization. We just need to sort the
        # events to create a deterministic timeline for final code generation.
        sorted_events = sorted(
            events,
            key=lambda e:
                (
                    e.timestamp_cycles,
                    0 if e.operation.operation_type == OperationType.RWG_INIT else 1,
                    e.operation.channel.global_id if e.operation.channel else ""
                )
        )
        
        last_op_end_time = 0
        for event in sorted_events:
            ts = event.timestamp_cycles
            
            # Calculate wait time based on when the hardware is actually free
            wait_cycles = ts - last_op_end_time
            
            if wait_cycles < 0:
                # This can happen if a pipelined LOAD is scheduled into a slot where
                # a previous operation is still running. We don't wait, but the 
                # actual start time of this event is pushed to when the board is free.
                wait_cycles = 0
            
            if wait_cycles > 0:
                board_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.WAIT_US, args=(cycles_to_us(wait_cycles),)))

            # Add the actual OASM calls for the current event
            board_calls.extend(event.oasm_calls)

            # The next operation can only start after the current one *actually* finishes.
            # The actual start time is the later of its scheduled time or when the board was last free.
            actual_start_time = max(ts, last_op_end_time)
            last_op_end_time = actual_start_time + event.cost_cycles

        calls_by_board[adr] = board_calls

    return calls_by_board

# Map OASMFunction enum members to actual OASM DSL functions
OASM_FUNCTION_MAP: Dict[OASMFunction, Callable] = {
    OASMFunction.TTL_CONFIG: ttl_config,
    OASMFunction.TTL_SET: ttl_set,
    OASMFunction.WAIT_US: wait_us,
    OASMFunction.WAIT_MASTER: wait_master,
    OASMFunction.TRIG_SLAVE: trig_slave,
    OASMFunction.RWG_INIT: rwg_init,
    OASMFunction.RWG_SET_CARRIER: rwg_set_carrier,
    OASMFunction.RWG_RF_SWITCH: rwg_rf_switch,
    OASMFunction.RWG_LOAD_WAVEFORM: rwg_load_waveform,
    OASMFunction.RWG_PLAY: rwg_play,
}

def execute_oasm_calls(calls_by_board: Dict[OASMAddress, List[OASMCall]], assembler_seq=None):
    """执行 OASM 调用序列并生成实际的 RTMQ 汇编代码
    
    Args:
        calls_by_board: Dict mapping board addresses to their OASM call lists
        assembler_seq: Pre-initialized OASM assembler sequence. If None, falls back to mock execution.
    """
    print("\n--- Executing OASM Calls ---")
    if not calls_by_board:
        print("No OASM calls to execute.")
        return True, assembler_seq
    
    # Count total calls across all boards
    total_calls = sum(len(calls) for calls in calls_by_board.values())
    print(f"Processing {total_calls} OASM calls across {len(calls_by_board)} boards")
    
    if assembler_seq is not None and OASM_AVAILABLE:
        print("🔧 Generating actual RTMQ assembly...")
        try:
            call_counter = 0
            assembler_seq.clear()
            # Process each board separately
            for board_adr, board_calls in calls_by_board.items():
                print(f"\n📋 Processing {len(board_calls)} calls for board '{board_adr.value}':")
                
                for call in board_calls:
                    call_counter += 1
                    func = OASM_FUNCTION_MAP.get(call.dsl_func)
                    if func is None:
                        print(f"Error: OASM function '{call.dsl_func.name}' not found in map.")
                        return False, assembler_seq
                    
                    args_str = ", ".join(map(str, call.args))
                    kwargs_str = ", ".join(f"{k}={v}" for k, v in call.kwargs.items()) if call.kwargs else ""
                    params_str = ", ".join(filter(None, [args_str, kwargs_str]))
                    print(f"  [{call_counter:02d}] {func.__name__}({params_str})")
                    
                    if call.kwargs:
                        assembler_seq(call.adr.value, func, *call.args, **call.kwargs)
                    else:
                        assembler_seq(call.adr.value, func, *call.args)
            
            # Generate assembly for each board
            for board_adr in calls_by_board.keys():
                board_name = board_adr.value
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
        success = _execute_oasm_calls_mock(calls_by_board)
        return success, None

def _execute_oasm_calls_mock(calls_by_board: Dict[OASMAddress, List[OASMCall]]) -> bool:
    """Mock execution fallback when OASM is not available"""
    try:
        call_counter = 0
        # Process each board separately
        for board_adr, board_calls in calls_by_board.items():
            print(f"\n📋 Mock execution for board '{board_adr.value}' ({len(board_calls)} calls):")
            
            for call in board_calls:
                call_counter += 1
                func = OASM_FUNCTION_MAP.get(call.dsl_func)
                if func is None:
                    print(f"Error: OASM function '{call.dsl_func.name}' not found in map.")
                    return False
                
                args_str = ", ".join(map(str, call.args))
                kwargs_str = ", ".join(f"{k}={v}" for k, v in call.kwargs.items()) if call.kwargs else ""
                params_str = ", ".join(filter(None, [args_str, kwargs_str]))
                print(f"  [{call_counter:02d}] {func.__name__}({params_str})")
                
                # Execute the mock function call
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