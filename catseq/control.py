"""
Control flow constructs using precompiled morphisms.

This module provides loop constructs and other control flow mechanisms
that leverage precompiled morphisms for efficient execution.
"""

from typing import Callable

from catseq.morphism import Morphism
from catseq.atomic import oasm_black_box
from catseq.compilation.compiler import compile_to_oasm_calls, OASM_FUNCTION_MAP
from catseq.compilation.types import OASMAddress, OASMCall, OASMFunction
from catseq.types.common import Channel, State, Board


def merge_and_group_values(*dictionaries: dict[Channel, State]) -> dict[Channel, tuple[State, State]]:
    """
    Merge start_state and end_state dictionaries for oasm_black_box channel_states.

    This function combines start_state and end_state dictionaries into the format
    required by oasm_black_box: {channel: (start_state, end_state)}

    Args:
        *dictionaries: Typically start_state_dict and end_state_dict

    Returns:
        A dictionary where each channel maps to (start_state, end_state) tuple
    """
    # Use a temporary dict to build incomplete tuples
    temp_dict: dict[Channel, tuple[State, ...]] = {}

    for dictionary in dictionaries:
        for key, value in dictionary.items():
            if key not in temp_dict:
                # First state for this channel
                temp_dict[key] = (value,)
            else:
                # Second state for this channel - complete the tuple
                existing_value = temp_dict[key]
                if len(existing_value) == 1:
                    temp_dict[key] = (existing_value[0], value)
                else:
                    # More than 2 states - this shouldn't happen for start/end states
                    raise ValueError(f"Channel {key} has more than 2 states")

    # Convert to final dict with complete tuples
    merged_dict: dict[Channel, tuple[State, State]] = {}
    for key, value in temp_dict.items():
        if len(value) == 2:
            merged_dict[key] = value  # type: ignore
        else:
            raise ValueError(f"Channel {key} is missing start or end state")

    return merged_dict


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


def create_precompiled_executor(precompiled_calls: dict[OASMAddress, list[OASMCall]]) -> Callable:
    """Create an executor function for precompiled OASM calls"""

    def executor():
        # This function will be executed in the assembler context
        # Iterate through all board calls (usually only one board)
        for _board_address, calls in precompiled_calls.items():
            for call in calls:
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

        # Create executor function
        board_funcs[board] = create_precompiled_executor(precompiled_calls)

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
        channel_states = merge_and_group_values(start_states, end_states)
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
    Simply repeat a morphism execution

    Args:
        morphism: Morphism to be repeated
        count: Number of repetitions
        assembler_seq: OASM assembler sequence

    Returns:
        Precompiled repeated execution blackbox Morphism
    """
    if count <= 0:
        raise ValueError("Repeat count must be positive")

    # Create repeated morphism
    repeated_morphism = morphism
    for _ in range(count - 1):
        repeated_morphism = repeated_morphism @ morphism

    # Get board functions and channel states
    board_funcs = compile_morphism_to_board_funcs(repeated_morphism, assembler_seq)
    channel_states = extract_channel_states_from_morphism(repeated_morphism)

    # Create blackbox Morphism
    return oasm_black_box(
        channel_states=channel_states,
        duration_cycles=repeated_morphism.total_duration_cycles,
        board_funcs=board_funcs
    )


def for_loop(
    body_morphism: Morphism,
    iterations: int,
    assembler_seq
) -> Morphism:
    """
    Create a precompiled for loop

    Args:
        body_morphism: Loop body Morphism
        iterations: Number of iterations
        assembler_seq: OASM assembler sequence

    Returns:
        Precompiled loop blackbox Morphism
    """
    if iterations <= 0:
        raise ValueError("Iterations must be positive")

    # For loop is essentially repeated execution
    return repeat_morphism(body_morphism, iterations, assembler_seq)


def while_loop(
    condition_morphism: Morphism,
    body_morphism: Morphism,
    max_iterations: int,
    assembler_seq
) -> Morphism:
    """
    Create a precompiled while loop

    Note: This is a simplified implementation that pre-expands the maximum iterations.
    Real conditional judgment needs to be implemented at runtime through hardware conditions.

    Args:
        condition_morphism: Condition check Morphism
        body_morphism: Loop body Morphism
        max_iterations: Maximum iterations (to prevent infinite loops)
        assembler_seq: OASM assembler sequence

    Returns:
        Precompiled loop blackbox Morphism
    """
    if max_iterations <= 0:
        raise ValueError("Max iterations must be positive")

    # Build loop: condition + body repeated execution
    loop_body = condition_morphism @ body_morphism
    full_loop = repeat_morphism(loop_body, max_iterations, assembler_seq)

    return full_loop