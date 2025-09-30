"""
OASM compiler for converting Morphism objects to OASM DSL calls.

This module provides the compilation logic for translating high-level
Morphism objects into concrete OASM DSL function calls. It uses a multi-pass
architecture to support pipelined operations and timing checks.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Callable, Union, Optional

from ..types.common import (
    OperationType, AtomicMorphism, Channel, TIMING_CRITICAL_OPERATIONS, OpaqueAtomicMorphism
)
from ..types.timing import LogicalTimestamp, TimestampType, is_same_epoch
from ..lanes import merge_board_lanes
from ..types.rwg import RWGActive
from ..time_utils import cycles_to_us
from .types import OASMAddress, OASMFunction, OASMCall
from .functions import (
    ttl_config,
    ttl_set,
    wait_us,
    wait_mu,
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

    # Populated by Pass 1 (Coloring)
    is_critical: bool = True
    
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

# --- Plan 3 Refactored Passes ---

def _pass1_extract_and_translate(morphism, verbose: bool = False) -> Dict[OASMAddress, List[LogicalEvent]]:
    """Pass 1: Extract events from morphism and translate to OASM calls (Plan 3)"""
    if verbose:
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
                operation=pop.operation,
                is_critical=(pop.operation.operation_type in TIMING_CRITICAL_OPERATIONS)
            )
            events_by_board[adr].append(event)
    
    for adr in events_by_board:
        events_by_board[adr].sort(key=lambda e: e.timestamp_cycles)
    
    # Step 2: Translate events to OASM calls (original Pass 1 logic with placeholder mechanism)
    if verbose:
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
                        # Generate separate OASM calls for each WaveformParams in pending_waveforms
                        # The OASM DSL function expects individual WaveformParams
                        if isinstance(op.end_state, RWGActive) and op.end_state.pending_waveforms:
                            for waveform_params in op.end_state.pending_waveforms:
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
                    # 根据板卡地址确定板卡类型
                    board_type = "main" if adr == OASMAddress.MAIN else "rwg"
                    for event in ts_events:
                        if event.operation.operation_type in [OperationType.TTL_ON, OperationType.TTL_OFF]:
                            event.oasm_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.TTL_SET, args=(mask, state_value, board_type)))
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

            # Handle Opaque OASM Functions (Black Boxes)
            opaque_events = [e for e in ts_events if isinstance(e.operation, OpaqueAtomicMorphism)]
            if opaque_events:
                first_op = opaque_events[0].operation
                func_id = id(first_op.user_func)

                # Validation: Ensure all simultaneous opaque ops on this board are the same
                for other_event in opaque_events[1:]:
                    if id(other_event.operation.user_func) != func_id:
                        raise ValueError(
                            f"Cannot execute two different black-box functions on the same board at the same time. "
                            f"Found {first_op.user_func.__name__} and {other_event.operation.user_func.__name__} at timestamp {ts}."
                        )
                
                # Generate one call for the entire group
                call = OASMCall(
                    adr=adr,
                    dsl_func=OASMFunction.USER_DEFINED_FUNC,
                    args=(first_op.user_func, first_op.user_args, first_op.user_kwargs)
                )
                opaque_events[0].oasm_calls.append(call)

    return events_by_board

def _pass2_cost_and_epoch_analysis(events_by_board: Dict[OASMAddress, List[LogicalEvent]], assembler_seq=None, verbose: bool = False):
    """Pass 2: Cost analysis and epoch detection (Plan 3)"""
    if verbose:
        print("Compiler Pass 2: Cost analysis and epoch detection...")
    
    # Step 1: Detect epoch boundaries GLOBALLY and assign logical timestamps
    if verbose:
        print("  Detecting epoch boundaries and assigning logical timestamps...")
    
    # Create a flat list of all events from all boards for global epoch detection
    all_events = [event for events in events_by_board.values() for event in events]
    
    # The _detect_epoch_boundaries function will modify the events in place,
    # which are shared with the original events_by_board dictionary.
    _detect_epoch_boundaries(all_events)

    # Print summary of epochs found on each board
    if verbose:
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

    # Step 2: Analyze costs for all operations
    if verbose:
        print("  Analyzing costs for all operations...")

    # First, handle opaque events which don't need an assembler
    for events in events_by_board.values():
        for event in events:
            if isinstance(event.operation, OpaqueAtomicMorphism):
                event.cost_cycles = event.operation.duration_cycles
                if verbose:
                    print(f"      - OPAQUE_OASM_FUNC at t={event.timestamp_cycles}: {event.cost_cycles} cycles (user-provided)")

    # Abort standard analysis if no assembler is available
    if assembler_seq is None:
        if OASM_AVAILABLE:
            if verbose:
                print("    Warning: No assembler provided. Standard cost analysis will be skipped.")
        else:
            if verbose:
                print("    Warning: OASM modules not available. Skipping cost analysis.")
        return

    # Now do standard cost analysis for all non-opaque events
    for adr, events in events_by_board.items():
        if verbose:
            print(f"    Analyzing costs for board {adr.value}...")
        for event in events:
            if isinstance(event.operation, OpaqueAtomicMorphism):
                continue  # Already handled

            if event.oasm_calls:
                event.cost_cycles = _analyze_operation_cost(event, adr, assembler_seq, verbose=verbose)
                if verbose:
                    print(f"      - {event.operation.operation_type.name} at t={event.timestamp_cycles}: {event.cost_cycles} cycles")
            else:
                event.cost_cycles = 0
                if verbose:
                    print(f"      - {event.operation.operation_type.name} at t={event.timestamp_cycles}: 0 cycles (no OASM calls)")

def _replace_wait_time_placeholders(events_by_board: Dict[OASMAddress, List[LogicalEvent]], verbose: bool = False):
    """
    Pass 5 Preview: Replace WAIT_TIME_PLACEHOLDER with calculated master wait times.
    
    This implements the basic logic from Plan 3 Pass 5:
    - Calculate the maximum end time of all operations in epoch=0
    - Replace TRIG_SLAVE placeholders with the calculated wait time
    """
    if verbose:
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
                    if verbose:
                        print(f"    Replaced placeholder in {adr.value} with wait time: {master_wait_time} cycles")
                else:
                    new_calls.append(call)
            event.oasm_calls = new_calls

def _pass3_schedule_and_optimize(events_by_board: Dict[OASMAddress, List[LogicalEvent]], verbose: bool = False):
    """
    Pass 3: Schedule & Optimize - Pipelining scheduler (New Plan)
    
    This pass implements the core pipelining optimization. It identifies LOAD-PLAY
    pairs and schedules the LOAD operation as late as possible before the PLAY
    operation, utilizing idle time.
    """
    if verbose:
        print("Compiler Pass 3: Scheduling with pipelining optimization...")
    
    for adr, events in events_by_board.items():
        # 1. 识别LOAD和PLAY操作
        # Note: _identify_pipeline_pairs is now used here for the main scheduling logic
        pipeline_pairs = _identify_pipeline_pairs(events, verbose=verbose)
        if not pipeline_pairs:
            continue
            
        if verbose:
            print(f"  Board {adr.value}: Found {len(pipeline_pairs)} pipeline pairs for optimization")
        
        # 2. 计算最优调度方案
        # This is the correct scheduling logic as per user's design intent
        optimized_events = _calculate_optimal_schedule(events, pipeline_pairs, verbose=verbose)
        
        # 3. 更新事件列表
        events_by_board[adr] = optimized_events
        if verbose:
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

def _pass4_validate_constraints(events_by_board: Dict[OASMAddress, List[LogicalEvent]], verbose: bool = False):
    """
    Pass 4: Constraint Validation (Plan 3)
    
    纯验证Pass，检查调度后的结果：
    1. 验证串行约束满足 - 确保同板卡LOAD操作确实被串行调度
    2. 验证deadline满足 - 每个LOAD都在对应PLAY前完成  
    3. 验证时序一致性 - 无负等待时间，时间线连续
    4. 验证跨epoch边界 - 调度优化没有违反epoch语义
    """
    if verbose:
        print("Compiler Pass 4: Validating constraints after scheduling (Plan 3)...")
    
    for adr, events in events_by_board.items():
        if verbose:
            print(f"  Validating board {adr.value}...")
        
        # 1. 验证串行约束
        _validate_serial_load_constraints(adr, events, verbose=verbose)
        
        # 2. 验证LOAD deadline满足
        _validate_load_deadlines(adr, events, verbose=verbose)
        
        # 3. 验证时序一致性
        _validate_timing_consistency(adr, events, verbose=verbose)
        
        # 4. 验证跨epoch边界（重用现有实现）
        _check_cross_epoch_violations_single_board(adr, events, verbose=verbose)

        # 5. 验证黑盒操作的板卡独占性
        _validate_black_box_exclusivity(adr, events, verbose=verbose)
        
        if verbose:
            print(f"    ✓ All constraints validated for board {adr.value}")


def _validate_black_box_exclusivity(adr, events: List[LogicalEvent], verbose: bool = False):
    """验证黑盒操作在执行期间是否独占板卡"""
    # 1. 识别出所有的黑盒事件和其他事件
    opaque_events = [e for e in events if isinstance(e.operation, OpaqueAtomicMorphism)]
    other_events = [e for e in events if not isinstance(e.operation, OpaqueAtomicMorphism)]

    if not opaque_events:
        return

    # 2. 获取所有不重复的黑盒时间窗口
    # Pass 1已经保证了同一时刻、同一板卡上的所有黑盒都属于同一个逻辑操作
    black_box_windows = {}
    for event in opaque_events:
        func_id = id(event.operation.user_func)
        if func_id not in black_box_windows:
            black_box_windows[func_id] = (event.timestamp_cycles, event.timestamp_cycles + event.cost_cycles)

    # 3. 检查其他事件是否与黑盒时间窗口重叠
    for start_A, end_A in black_box_windows.values():
        for event_B in other_events:
            start_B = event_B.timestamp_cycles
            end_B = start_B + event_B.cost_cycles

            # Overlap check: (StartA < EndB) and (EndA > StartB)
            if (start_A < end_B) and (end_A > start_B):
                raise ValueError(
                    f"Constraint violation on board {adr.value}: Operation {event_B.operation} at t={start_B}c "
                    f"conflicts with a black-box operation running in window [{start_A}c, {end_A}c]. "
                    f"Black-box operations require exclusive access to the board."
                )
    
    if verbose:
        print(f"    ✓ Black-box exclusivity validated ({len(black_box_windows)} block(s))")


def _validate_serial_load_constraints(adr, events: List[LogicalEvent], verbose: bool = False):
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
    
    if verbose:
        print(f"    ✓ Serial LOAD constraints satisfied ({len(load_events)} operations)")

def _validate_load_deadlines(adr, events: List[LogicalEvent], verbose: bool = False):
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
    
    if verbose:
        print(f"    ✓ LOAD deadlines satisfied ({len(load_play_pairs)} pairs)")

def _validate_timing_consistency(adr, events: List[LogicalEvent], verbose: bool = False):
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
    
    if verbose:
        print(f"    ✓ Timing consistency validated ({len(events)} events)")

def _check_cross_epoch_violations_single_board(adr, events: List[LogicalEvent], verbose: bool = False):
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
    
    if verbose:
        print(f"    ✓ Cross-epoch boundaries validated ({len(epochs)} epochs)")

# --- Helper Functions for Cost Analysis ---

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

def _analyze_operation_cost(event: LogicalEvent, adr: OASMAddress, assembler_seq, verbose: bool = False) -> int:
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
        if verbose:
            print(f"      Warning: Cost analysis failed for {event.operation.operation_type.name}: {e}")
        return 0

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

def _identify_pipeline_pairs(events: List[LogicalEvent], verbose: bool = False) -> List[PipelinePair]:
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
            if not event.is_critical and event.operation.operation_type == OperationType.RWG_LOAD_COEFFS:
                # Look for the next UPDATE_PARAMS on the same channel
                for j in range(i + 1, len(channel_events)):
                    next_event = channel_events[j]
                    if next_event.operation.operation_type == OperationType.RWG_UPDATE_PARAMS:
                        # Found the corresponding PLAY event
                        pair = PipelinePair(load_event=event, play_event=next_event)
                        pairs.append(pair)
                        if verbose:
                            print(f"    Found pipeline pair: LOAD@{event.timestamp_cycles}c → PLAY@{next_event.timestamp_cycles}c on {channel.global_id}")
                        break
    
    return pairs


def _calculate_optimal_schedule(events: List[LogicalEvent], pipeline_pairs: List[PipelinePair], verbose: bool = False) -> List[LogicalEvent]:
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

    if verbose:
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

        if verbose:
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


def _pass4_generate_oasm_calls(events_by_board: Dict[OASMAddress, List[LogicalEvent]], verbose: bool = False) -> Dict[OASMAddress, List[OASMCall]]:
    """
    Pass 4: Generates the final scheduled OASM calls from the enriched
    logical events, including intelligent pipeline scheduling optimization.
    """
    if verbose:
        print("Compiler Pass 4: Generating and scheduling OASM calls...")
    calls_by_board: Dict[OASMAddress, List[OASMCall]] = {}
    
    # User-managed synchronization: sync operations are explicitly added by user via global_sync()
    board_addresses = list(events_by_board.keys())
    if verbose:
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
                board_calls.append(OASMCall(adr=adr, dsl_func=OASMFunction.WAIT, args=(wait_cycles,)))

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
    OASMFunction.WAIT: wait_mu,
    OASMFunction.WAIT_MASTER: wait_master,
    OASMFunction.TRIG_SLAVE: trig_slave,
    OASMFunction.RWG_INIT: rwg_init,
    OASMFunction.RWG_SET_CARRIER: rwg_set_carrier,
    OASMFunction.RWG_RF_SWITCH: rwg_rf_switch,
    OASMFunction.RWG_LOAD_WAVEFORM: rwg_load_waveform,
    OASMFunction.RWG_PLAY: rwg_play,
}

# --- Main Compiler Entry Point ---

def compile_to_oasm_calls(morphism, assembler_seq=None, _return_internal_events=False, verbose: bool = False) -> Union[Dict[OASMAddress, List[OASMCall]], Dict[OASMAddress, List[LogicalEvent]]]:
    """Drives the Plan 3 five-pass compilation process.
    
    Args:
        morphism: The morphism to compile
        assembler_seq: Pre-initialized OASM assembler sequence for cost analysis.
                      If None, cost analysis will be skipped when OASM is not available.
        _return_internal_events: For testing, return internal events instead of calls
        verbose: If True, print detailed debugging information during compilation.
    """
    
    # Pass 1: Extract events from morphism and translate to OASM calls (Plan 3)
    events_by_board = _pass1_extract_and_translate(morphism, verbose=verbose)
    
    # Pass 2: Cost analysis and epoch detection (Plan 3)
    _pass2_cost_and_epoch_analysis(events_by_board, assembler_seq, verbose=verbose)
    
    # Pass 3: Schedule & Optimize (Plan 3 implementation)
    _pass3_schedule_and_optimize(events_by_board, verbose=verbose)
    
    # Pass 4: Constraint Validation (Plan 3 - pure validation after scheduling)
    _pass4_validate_constraints(events_by_board, verbose=verbose)

    # For testing purposes, allow returning the internal event list
    if _return_internal_events:
        return events_by_board
    
    # Pass 5: Final Code Generation (Plan 3)
    oasm_calls = _pass5_generate_final_calls(events_by_board, verbose=verbose)
    
    return oasm_calls

def _pass5_generate_final_calls(events_by_board: Dict[OASMAddress, List[LogicalEvent]], verbose: bool = False) -> Dict[OASMAddress, List[OASMCall]]:
    """
    Pass 5: Final Code Generation (Plan 3)
    
    完成最终代码生成：
    1. 计算最终master wait time
    2. 替换所有WAIT_TIME_PLACEHOLDER  
    3. 生成最终OASMCall序列
    """
    if verbose:
        print("Compiler Pass 5: Final code generation with placeholder replacement (Plan 3)...")
    
    # Step 1: 替换WAIT_TIME_PLACEHOLDER
    _replace_wait_time_placeholders(events_by_board, verbose=verbose)
    
    # Step 2: 生成最终OASM调用序列（重用现有实现）
    if verbose:
        print("  Generating final OASM call sequence...")
    oasm_calls = _pass4_generate_oasm_calls(events_by_board, verbose=verbose)
    
    return oasm_calls

def execute_oasm_calls(calls_by_board: Dict[OASMAddress, List[OASMCall]], assembler_seq=None, verbose: bool = False):
    """执行 OASM 调用序列并生成实际的 RTMQ 汇编代码
    
    Args:
        calls_by_board: Dict mapping board addresses to their OASM call lists
        assembler_seq: Pre-initialized OASM assembler sequence. If None, falls back to mock execution.
    """
    if verbose:
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
                print(f"📋 Processing {len(board_calls)} calls for board '{board_adr.value}':")
                
                for call in board_calls:
                    call_counter += 1

                    # Handle user-defined black-box functions differently from standard functions
                    if call.dsl_func == OASMFunction.USER_DEFINED_FUNC:
                        # For black boxes, the function and its args are packed inside the call's args
                        user_func, user_args, user_kwargs = call.args
                        if verbose:
                            print(f"  [{call_counter:02d}] Executing black-box function: {user_func.__name__}")
                        # The user function is passed into the assembler sequence to be executed
                        assembler_seq(call.adr.value, user_func, *user_args, **user_kwargs)
                    else:
                        # For standard functions, look up the function in the map
                        func = OASM_FUNCTION_MAP.get(call.dsl_func)
                        if func is None:
                            print(f"Error: OASM function '{call.dsl_func.name}' not found in map.")
                            return False, assembler_seq
                        
                        if verbose:
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
                if verbose:
                    print(f"\n📋 Generated RTMQ assembly for {board_name}:")
                try:
                    if OASM_AVAILABLE:
                        asm_lines = disassembler(core=C_RWG)(assembler_seq.asm[board_name])
                        if verbose:
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
