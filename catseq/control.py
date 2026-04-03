"""
Control flow constructs using precompiled morphisms.

This module provides loop constructs and other control flow mechanisms
that leverage precompiled morphisms for efficient execution.
"""

from typing import Callable

from catseq.morphism import Morphism
from catseq.atomic import oasm_black_box
from catseq.compilation.compiler import (
    compile_to_oasm_calls,
    OASM_FUNCTION_MAP,
    OASM_AVAILABLE,
    execute_oasm_calls,
    RTMQ_INSTRUCTION_COSTS,
    _calculate_gap_cycles,
)
from catseq.compilation.types import OASMFunction
from catseq.types.common import Channel, State, Board

# Import OASM loop control and analysis functions
from oasm.rtmq2 import for_, end, R, disassembler, Func, call, function as rtmq_function
from oasm.dev.rwg import C_RWG


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

def _parse_tim_value(value_str: str) -> int:
    """Parse TIM immediate value (supports hex with underscores or decimal)."""
    try:
        # int(..., 0) 支持 0x 前缀和下划线分隔
        return int(value_str.replace("_", ""), 0)
    except ValueError:
        return 0

def _estimate_oasm_cost_with_timer(asm_lines: list[str]) -> int:
    """
    Estimate execution cycles from RTMQ assembly, with correct handling of TIM/NOP H timer blocks.

    规则（基于 StdCohNode 文档）：
    - 普通指令：记为 1 个周期（忽略流水线细节）
    - 计时结构：
        CLO - TIM T
        ... (中间指令总耗时不超过 T-2 周期)
        NOP H
      整个结构视为 **精确 T 个周期**。
    """
    total_cycles = 0

    timer_active = False
    timer_value: int | None = None

    # 参考编译器中的 _estimate_oasm_cost：跟踪最近指令用于 gap cycle 计算
    instruction_history: list[tuple[str, str, int]] = []

    for line in asm_lines:
        parts = line.strip().split()
        if not parts:
            continue

        instr = parts[0].upper()
        flag = parts[1].upper() if len(parts) > 1 else "-"
        target = parts[2].upper() if len(parts) > 2 else ""

        # 计时结构：从 CLO - TIM T 到 NOP H
        if not timer_active:
            # 检测 CLO - TIM T，进入计时块
            if instr == "CLO" and target == "TIM" and len(parts) >= 4:
                timer_value = _parse_tim_value(parts[3])
                timer_active = True
                # CLO - TIM 自身不单独计入 1cycle，而是包含在 T 里
                # 为了避免计时块对后续 gap 计算产生影响，清空历史
                instruction_history.clear()
                continue

            # --- 非计时块普通指令：参考 _estimate_oasm_cost 的做法 ---

            # 特殊情况：跳转（写 PTR 且带 P 标志）总是 10 cycles
            if instr in {"AMK", "CLO"} and target == "PTR" and flag == "P":
                total_cycles += 10
                instruction_history.append(("JUMP_PTR", target, 0))
                if len(instruction_history) > 3:
                    instruction_history.pop(0)
                continue

            # 基础指令开销
            cost = RTMQ_INSTRUCTION_COSTS.get(instr, 1)

            # P 标志：额外 6 个周期（NOP P 等）
            if flag == "P":
                cost += 6

            # 流水线 gap cycles
            gap_cycles = _calculate_gap_cycles(instr, target, instruction_history)

            total_cycles += cost + gap_cycles

            # 维护有限长度的指令历史
            instruction_history.append((instr, target, 0))
            if len(instruction_history) > 3:
                instruction_history.pop(0)

        else:
            # 已在计时块中，直到 NOP H 结束
            if instr == "NOP" and flag == "H":
                # 计时结构总耗时 = T 个周期
                if timer_value is not None and timer_value > 0:
                    total_cycles += timer_value
                else:
                    # 解析失败时保守按 1 cycle 处理
                    total_cycles += 1

                timer_active = False
                timer_value = None

                # 计时块结束后清空历史，避免计时块内部指令影响后续 gap 计算
                instruction_history.clear()
                continue

            # 计时块内部其它指令成本由 T 覆盖，这里不再累加
            continue

    return total_cycles

def _estimate_morphism_cycles_from_assembly(
    morphism: Morphism,
    assembler_seq,
) -> int:
    """
    Estimate morphism execution time per iteration (in cycles) from compiled RTMQ assembly.

    If OASM is not available or compilation fails, falls back to morphism.total_duration_cycles.
    """
    # If we don't have an assembler or OASM support, fall back to logical duration
    if assembler_seq is None or not OASM_AVAILABLE:
        return morphism.total_duration_cycles

    try:
        # 1. Compile Morphism to final scheduled OASM calls
        calls_by_board = compile_to_oasm_calls(morphism, assembler_seq)

        # 2. Execute OASM calls into the assembler to generate binary assembly
        success, _ = execute_oasm_calls(calls_by_board, assembler_seq, clear=True, verbose=False)
        if not success:
            print("========not_success=======")
            return morphism.total_duration_cycles

        # 3. Disassemble and estimate cost from RTMQ assembly for each board
        max_cost = 0
        for board_adr in calls_by_board.keys():
            board_name = board_adr.value
            # print(board_adr)
            try:
                binary_asm = assembler_seq.asm[board_name]
            except Exception:
                continue

            try:
                asm_lines = disassembler(core=C_RWG)(binary_asm)
                # for line in asm_lines:
                #     print(line)
            except Exception:
                continue

            cost = _estimate_oasm_cost_with_timer(asm_lines)
            if cost > max_cost:
                max_cost = cost

        return max_cost or morphism.total_duration_cycles
    except Exception:
        # On any unexpected error, be conservative and fall back
        return morphism.total_duration_cycles



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
    # Get morphism timing (from compiled assembly) and channel states
    t_morphism = _estimate_morphism_cycles_from_assembly(morphism, assembler_seq)
    # print(t_morphism)
    # t_morphism = morphism.total_duration_cycles
    channel_states = extract_channel_states_from_morphism(morphism)

    # Calculate total execution time using the loop timing formula:
    # Total = 15 + n*(26 + t_morphism)
    # Where:
    # - 15: Fixed overhead (2 cycles init + 13 cycles final condition check)
    # - n: Number of iterations
    # - 26: Per-iteration overhead (13 cycles condition + 13 cycles increment/jump)
    # - t_morphism: Morphism execution time per iteration
    LOOP_FIXED_OVERHEAD = 15
    if count >= 128:
        LOOP_PER_ITERATION_OVERHEAD = 25
    else:
        LOOP_PER_ITERATION_OVERHEAD = 24

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

def function_def_morphism(
    morphism: Morphism,
    name: str,
    assembler_seq,
) -> Morphism:
    """
    Construct a hardware-level Morphism that defines a reusable function.

    This function generates a 'blackbox' Morphism that encapsulates the logic
    of the input morphism under a specific name. It prepares the structure
    for hardware-level function definition, calculating the necessary timing
    overhead and mapping the internal logic to board-specific execution functions.

    Args:
        morphism: The Morphism object containing the logic to be defined as a function.
        name: The identifier (symbol) to assign to this function definition.
        assembler_seq: The OASM assembler sequence used for timing estimation.

    Returns:
        A Blackbox Morphism representing the function definition, including
        updated channel states and total cycle duration.
    """

    # Estimate the execution time of the morphism body based on assembly instructions
    t_morphism = _estimate_morphism_cycles_from_assembly(morphism, assembler_seq)
    
    # Extract the input/output channel states to ensure the blackbox preserves interface compatibility
    channel_states = extract_channel_states_from_morphism(morphism)

    # Define the fixed cycle overhead required for function definition instructions
    LOOP_FIXED_OVERHEAD = 26

    # Calculate total duration: overhead + internal logic duration
    total_duration_cycles = LOOP_FIXED_OVERHEAD + t_morphism

    # Compile the morphism into executable board-specific functions
    base_board_funcs = compile_morphism_to_board_funcs(morphism, assembler_seq)

    # Create board functions that implement the function definition logic
    def create_loop_executor(base_func):
        """
        Create an executor function that wraps the logic with definition markers.
        Note: This uses '_start' as the entry point and 'rtmq_function' to finalize the definition.
        """
        def func_executor():
            call("_start")
            with Func(name,2,2):
                # Execute the core logic of the morphism
                base_func()
            rtmq_function("_start")

        return func_executor

    # Wrap the base functions with the definition logic for each board
    board_funcs = {}
    for board, base_func in base_board_funcs.items():
        board_funcs[board] = create_loop_executor(base_func)

    # Return the final blackbox Morphism with timing and metadata
    return oasm_black_box(
        channel_states=channel_states,
        duration_cycles=total_duration_cycles,
        board_funcs=board_funcs,
        metadata={
            'blackbox_type': 'function define',
            'unit_duration': t_morphism
        }
    )

def function_call_morphism(
    morphism: Morphism,
    name: str,
    assembler_seq,
) -> Morphism:
    """
    Construct a hardware-level Morphism that invokes a previously defined function.

    This function generates a 'blackbox' Morphism that represents a function call
    instruction. It calculates the timing cost of the call (overhead + estimated body duration)
    and creates a stub that issues the hardware call instruction using the provided name.

    Args:
        morphism: The reference Morphism used to determine timing and interface characteristics.
        name: The identifier of the function to be called.
        assembler_seq: The OASM assembler sequence used for timing estimation.

    Returns:
        A Blackbox Morphism representing the function call operation.
    """
    # Estimate the duration of the function body to account for total call time
    t_morphism = _estimate_morphism_cycles_from_assembly(morphism, assembler_seq)
    
    # Retrieve channel states to maintain consistency with the function signature
    channel_states = extract_channel_states_from_morphism(morphism)
    
    # Define the fixed cycle overhead for the hardware call instruction
    CALL_FIXED_OVERHEAD = 26
    
    # Total duration includes the call overhead plus the estimated function execution time
    total_duration_cycles = CALL_FIXED_OVERHEAD + t_morphism

    # Get the base board functions to determine target hardware boards
    base_board_funcs = compile_morphism_to_board_funcs(morphism, assembler_seq)

    # Create board functions that implement the hardware call instruction
    def create_loop_executor():
        """
        Create an executor function that issues the 'call' instruction.
        """
        def func_executor():
            # Issue the hardware call to the specified function name
            call(name)

        return func_executor

    # Generate the execution stubs for the relevant boards
    board_funcs = {}
    for board in base_board_funcs.keys():
        board_funcs[board] = create_loop_executor()

    # Return the blackbox Morphism representing the function call
    return oasm_black_box(
        channel_states=channel_states,
        duration_cycles=total_duration_cycles,
        board_funcs=board_funcs,
        metadata={
            'blackbox_type': 'function call',
            'unit_duration': t_morphism
        }
    )