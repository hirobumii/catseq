"""
Control flow constructs using precompiled morphisms.

This module provides loop constructs and other control flow mechanisms
that leverage precompiled morphisms for efficient execution.
"""

from typing import Callable

from catseq.morphism import Morphism
from catseq.atomic import oasm_black_box
from catseq.compilation.compiler import compile_to_oasm_calls, OASM_FUNCTION_MAP
from catseq.compilation.types import OASMFunction
from catseq.types.common import Channel, State, Board

# Import OASM loop control functions
from oasm.rtmq2 import for_, end, R


def extract_channel_states_from_morphism(morphism: Morphism) -> dict[Channel, tuple[State, State]]:
    """Extract start and end states for each channel from a Morphism"""
    channel_states = {}

    for channel, lane in morphism.lanes.items():
        if lane.operations:
            # Get the first and last operation states
            first_op = lane.operations[0]
            last_op = lane.operations[-1]

            start_state = first_op.start_state
            end_state = last_op.end_state

            channel_states[channel] = (start_state, end_state)

    return channel_states


def compile_morphism_to_board_funcs(
    morphism: Morphism,
    assembler_seq
) -> dict[Board, Callable]:
    """
    Compile a morphism to board functions dict for oasm_black_box.

    Args:
        morphism: Source Morphism to be compiled
        assembler_seq: OASM assembler sequence

    Returns:
        Dictionary mapping each board to its precompiled executor function
    """
    # Decompose morphism by board
    lanes_by_board = morphism.lanes_by_board()

    # Create executor function for each board
    board_funcs = {}

    for board, board_lanes in lanes_by_board.items():
        # Repackage as single-board Morphism
        sub_morphism = Morphism(lanes=board_lanes)

        # Precompile to OASM calls
        precompiled_calls = compile_to_oasm_calls(sub_morphism, assembler_seq)

        # Create executor function directly (inline the old create_precompiled_executor)
        def create_executor(calls):
            def executor():
                # Execute all board calls
                for calls_list in calls.values():
                    for call in calls_list:
                        if call.dsl_func == OASMFunction.USER_DEFINED_FUNC:
                            # Handle nested user function calls
                            user_func, user_args, user_kwargs = call.args
                            user_func(*user_args, **user_kwargs)
                        else:
                            # Standard OASM function calls
                            func = OASM_FUNCTION_MAP[call.dsl_func]
                            if call.kwargs:
                                func(*call.args, **call.kwargs)
                            else:
                                func(*call.args)
            return executor

        board_funcs[board] = create_executor(precompiled_calls)

    return board_funcs


def morphism_to_precompiled_blackbox(
    morphism: Morphism,
    assembler_seq,
    get_start_state_func: Callable = None,
    get_end_state_func: Callable = None
) -> Morphism:
    """
    Convert a Morphism to a precompiled blackbox Morphism

    Args:
        morphism: Source Morphism to be precompiled
        assembler_seq: OASM assembler sequence (for precompilation)
        get_start_state_func: Function to get start states (optional)
        get_end_state_func: Function to get end states (optional)

    Returns:
        New Morphism wrapped as a blackbox
    """

    # 1. Compile morphism to board functions
    board_funcs = compile_morphism_to_board_funcs(morphism, assembler_seq)

    # 2. Extract channel states
    if get_start_state_func and get_end_state_func:
        start_states = get_start_state_func(morphism)
        end_states = get_end_state_func(morphism)
        # Inline merge logic - combine start and end states
        channel_states = {}
        for channel in set(start_states.keys()) | set(end_states.keys()):
            if channel in start_states and channel in end_states:
                channel_states[channel] = (start_states[channel], end_states[channel])
            else:
                raise ValueError(f"Channel {channel} is missing start or end state")
    else:
        channel_states = extract_channel_states_from_morphism(morphism)

    # 3. Create blackbox Morphism
    return oasm_black_box(
        channel_states=channel_states,
        duration_cycles=morphism.total_duration_cycles,
        board_funcs=board_funcs
    )


def repeat_morphism(
    morphism: Morphism,
    count: int,
    assembler_seq
) -> Morphism:
    """
    Create a true hardware loop that repeats a morphism execution n times.

    This function creates a blackbox morphism that implements hardware-level looping
    using OASM for_ and end instructions with correct timing calculation.

    Args:
        morphism: Morphism to be repeated
        count: Number of repetitions (n)
        assembler_seq: OASM assembler sequence

    Returns:
        Blackbox Morphism that repeats the input morphism n times with correct timing
    """
    if count <= 0:
        raise ValueError("Repeat count must be positive")

    # Get morphism timing and channel states
    t_morphism = morphism.total_duration_cycles
    channel_states = extract_channel_states_from_morphism(morphism)

    # Calculate total execution time using the loop timing formula:
    # Total = 15 + n*(26 + t_morphism)
    # Where:
    # - 15: Fixed overhead (2 cycles init + 13 cycles final condition check)
    # - n: Number of iterations
    # - 26: Per-iteration overhead (13 cycles condition + 13 cycles increment/jump)
    # - t_morphism: Morphism execution time per iteration
    LOOP_FIXED_OVERHEAD = 15
    LOOP_PER_ITERATION_OVERHEAD = 26

    total_duration_cycles = LOOP_FIXED_OVERHEAD + count * (LOOP_PER_ITERATION_OVERHEAD + t_morphism)

    # Get the base board functions from the morphism
    base_board_funcs = compile_morphism_to_board_funcs(morphism, assembler_seq)

    # Create board functions that implement the hardware loop
    def create_loop_executor(base_func):
        """Create executor function that implements the hardware loop using for_ and end"""
        def loop_executor():
            # Generate the hardware loop structure:
            # for_(register, count) - creates loop initialization and condition
            for_(R[1], count)  # Use register R[1] for loop counter, repeat 'count' times

            # Execute the morphism content inside the loop
            base_func()

            # Close the loop
            end()

        return loop_executor

    # Create board functions with loop execution
    board_funcs = {}
    for board, base_func in base_board_funcs.items():
        board_funcs[board] = create_loop_executor(base_func)

    # Create blackbox Morphism with correct timing and loop metadata
    return oasm_black_box(
        channel_states=channel_states,
        duration_cycles=total_duration_cycles,
        board_funcs=board_funcs,
        metadata={
            'loop_type': 'repeat',
            'loop_count': count,
            'unit_duration': t_morphism
        }
    )
