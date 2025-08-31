#!/usr/bin/env python3
"""
Simple debug test for CatSeq framework
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from catseq.types import Board, Channel
from catseq.atomic import ttl_init, ttl_on, wait
from catseq.morphism import from_atomic

def test_simple_sequence():
    print("Creating simple test...")
    
    # Create board and channel
    board = Board("test")
    channel = Channel(board, 0)
    
    # Create operations
    init_op = ttl_init(channel)
    wait_op = wait(100.0)  # 100μs
    on_op = ttl_on(channel)
    
    print(f"init_op: {init_op} - duration: {init_op.duration_cycles} cycles")
    print(f"wait_op: {wait_op} - duration: {wait_op.duration_cycles} cycles")
    print(f"on_op: {on_op} - duration: {on_op.duration_cycles} cycles")
    
    # Try simple sequence
    print("\nCreating simple sequence...")
    simple_sequence = from_atomic(init_op) @ from_atomic(wait_op) @ from_atomic(on_op)
    
    print(f"Simple sequence duration: {simple_sequence.total_duration_us:.1f}μs")
    print(f"Simple sequence lanes: {len(simple_sequence.lanes)}")
    
    for channel, lane in simple_sequence.lanes.items():
        print(f"  Channel {channel}: {lane.total_duration_us:.1f}μs with {len(lane.operations)} operations")
        for i, op in enumerate(lane.operations):
            print(f"    Op {i}: {op} - duration: {op.duration_cycles} cycles")
        print(f"    Lane total: {lane.total_duration_cycles} cycles")

if __name__ == "__main__":
    test_simple_sequence()