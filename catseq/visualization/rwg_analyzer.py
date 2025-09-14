"""
RWG Timeline Analysis Module

Provides functions for analyzing RWG operation sequences and constructing continuous timelines.
"""

from typing import List, Dict, Optional, Tuple
from ..lanes import PhysicalOperation
from ..types.common import OperationType
from ..time_utils import cycles_to_us


def _evaluate_taylor_series(coeffs: Tuple, t: float) -> float:
    """Calculate Taylor series value at time t"""
    if not coeffs:
        return 0.0
    
    result = coeffs[0] if coeffs[0] is not None else 0.0
    for i, coeff in enumerate(coeffs[1:], 1):
        if coeff is not None:
            result += coeff * (t ** i)
    return result


def _find_previous_load(ops: List[PhysicalOperation]) -> Optional[PhysicalOperation]:
    """Find the most recent LOAD operation from the operation list"""
    for op in reversed(ops):
        if op.operation.operation_type == OperationType.RWG_LOAD_COEFFS:
            return op
    return None


def analyze_rwg_timeline(ops: List[PhysicalOperation], curve_type: str) -> List[Dict]:
    """Analyze RWG operation sequence and construct complete frequency/amplitude timeline
    
    Args:
        ops: Physical operation sequence
        curve_type: "freq" or "amp"
    
    Returns:
        List of time segments, each containing type, start_time, end_time, etc.
    """
    # State tracking
    current_rf_state = False
    current_static_value = 0.0
    
    
    # Event collection: record all state changes in chronological order
    events = []
    
    for i, op in enumerate(ops):
        op_time = op.timestamp_us
        
        # Update static value (from any RWGActive state's snapshot)
        if hasattr(op.operation, 'end_state') and hasattr(op.operation.end_state, 'snapshot'):
            snapshot = op.operation.end_state.snapshot
            if snapshot:
                new_value = snapshot[0].freq if curve_type == "freq" else snapshot[0].amp
                if new_value != current_static_value:
                    current_static_value = new_value
                    events.append({
                        'time': op_time,
                        'type': 'value_change',
                        'value': current_static_value
                    })
        
        # RF state changes
        if op.operation.operation_type == OperationType.RWG_RF_SWITCH:
            if hasattr(op.operation, 'end_state'):
                new_rf_state = op.operation.end_state.rf_on
                if new_rf_state != current_rf_state:
                    current_rf_state = new_rf_state
                    events.append({
                        'time': op_time,
                        'type': 'rf_change',
                        'rf_on': current_rf_state
                    })
        
        # Ramp operations
        elif (op.operation.operation_type == OperationType.RWG_UPDATE_PARAMS and 
              op.operation.duration_cycles > 0):
            duration_us = cycles_to_us(op.operation.duration_cycles)
            
            # Find paired LOAD operation to get coefficients
            paired_load = _find_previous_load(ops[:i])
            ramp_coeffs = None
            if paired_load and hasattr(paired_load.operation.end_state, 'pending_waveforms'):
                waveforms = paired_load.operation.end_state.pending_waveforms
                if waveforms:
                    ramp_coeffs = waveforms[0].freq_coeffs if curve_type == "freq" else waveforms[0].amp_coeffs
            
            events.append({
                'time': op_time,
                'type': 'ramp_start',
                'duration': duration_us,
                'coeffs': ramp_coeffs
            })
            
            events.append({
                'time': op_time + duration_us,
                'type': 'ramp_end',
                'coeffs': ramp_coeffs  # Keep coeffs to calculate end value
            })
    
    # Sort events by time
    events.sort(key=lambda e: e['time'])
    
    
    # Build time segments
    segments = []
    segment_start = 0.0
    is_in_ramp = False
    current_rf_state = False  # Re-initialize
    current_static_value = 0.0
    current_ramp_coeffs = None
    
    # Add timeline end point
    timeline_end = max(op.timestamp_us for op in ops) if ops else 0.0
    events.append({'time': timeline_end, 'type': 'end'})
    
    for event in events:
        event_time = event['time']
        
        # Before event occurs, add current state segment (only when RF is ON)
        if event_time > segment_start and current_rf_state:
            if is_in_ramp:
                # Currently in ramp segment
                segments.append({
                    'type': 'ramp',
                    'start_time': segment_start,
                    'end_time': event_time,
                    'coeffs': current_ramp_coeffs,
                    'rf_on': current_rf_state
                })
            else:
                # Currently in static segment
                segments.append({
                    'type': 'static',
                    'start_time': segment_start,
                    'end_time': event_time,
                    'value': current_static_value,
                    'rf_on': current_rf_state
                })
        
        # Process event
        if event['type'] == 'value_change':
            current_static_value = event['value']
        elif event['type'] == 'rf_change':
            current_rf_state = event['rf_on']
        elif event['type'] == 'ramp_start':
            is_in_ramp = True
            current_ramp_coeffs = event['coeffs']
        elif event['type'] == 'ramp_end':
            is_in_ramp = False
            # Calculate the end value of the ramp and update static value
            if 'coeffs' in event and event['coeffs']:
                duration = event_time - segment_start  # Duration of the ramp that just ended
                current_static_value = _evaluate_taylor_series(event['coeffs'], duration)
        
        segment_start = event_time
    
    return segments