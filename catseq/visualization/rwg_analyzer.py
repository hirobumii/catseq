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
        
        # PLAY operations (all RWG_UPDATE_PARAMS, duration is always 0)
        elif op.operation.operation_type == OperationType.RWG_UPDATE_PARAMS:
            # Find paired LOAD operation to get coefficients
            paired_load = _find_previous_load(ops[:i])
            coeffs = None
            if paired_load and hasattr(paired_load.operation.end_state, 'pending_waveforms'):
                waveforms = paired_load.operation.end_state.pending_waveforms
                if waveforms:
                    coeffs = waveforms[0].freq_coeffs if curve_type == "freq" else waveforms[0].amp_coeffs

            # Find next PLAY operation to determine segment duration
            next_play_time = None
            for j in range(i + 1, len(ops)):
                next_op = ops[j]
                if next_op.operation.operation_type == OperationType.RWG_UPDATE_PARAMS:
                    next_play_time = next_op.timestamp_us
                    break

            events.append({
                'time': op_time,
                'type': 'play_start',
                'coeffs': coeffs,
                'next_play_time': next_play_time
            })

            # Add segment end event
            if next_play_time:
                events.append({
                    'time': next_play_time,
                    'type': 'play_end'
                })
    
    # Sort events by time
    events.sort(key=lambda e: e['time'])
    
    
    # Build time segments
    segments = []
    current_rf_state = False  # Re-initialize
    current_coeffs = None

    # Add timeline end point
    timeline_end = max(op.timestamp_us for op in ops) if ops else 0.0
    events.append({'time': timeline_end, 'type': 'end'})

    # Process events to build segments
    for i, event in enumerate(events):
        event_time = event['time']

        # Process event
        if event['type'] == 'rf_change':
            current_rf_state = event['rf_on']
        elif event['type'] == 'play_start':
            current_coeffs = event['coeffs']
            next_play_time = event.get('next_play_time')

            # Create segment from this PLAY to next PLAY (or timeline end)
            if next_play_time:
                segment_end_time = next_play_time
            else:
                segment_end_time = timeline_end

            # Only add segment if RF is ON and we have a valid time range
            if current_rf_state and segment_end_time > event_time:
                # Calculate the interpolation duration (from this PLAY to next PLAY)
                interpolation_duration = segment_end_time - event_time

                segments.append({
                    'type': 'interpolation',  # From current PLAY to next PLAY
                    'start_time': event_time,
                    'end_time': segment_end_time,
                    'coeffs': current_coeffs,
                    'rf_on': True,
                    'interpolation_duration': interpolation_duration
                })
        elif event['type'] == 'value_change':
            # Handle static value changes from snapshots
            # These represent immediate value updates when RF is on
            if current_rf_state:
                segments.append({
                    'type': 'static',
                    'start_time': event_time,
                    'end_time': event_time,  # Instantaneous change
                    'value': event['value'],
                    'rf_on': True
                })
    
    return segments