"""
RTMQ timing and cost-analysis helpers.
"""

from typing import List

from ..types.common import OperationType
from .execution import OASM_FUNCTION_MAP
from .types import OASMAddress

try:
    from oasm.rtmq2 import disassembler
    from oasm.dev.rwg import C_RWG
except ImportError:
    disassembler = None
    C_RWG = None


RTMQ_INSTRUCTION_COSTS = {
    "CHI": 1,
    "CLO": 1,
    "AMK": 1,
    "SFS": 1,
    "NOP": 1,
    "CSR": 1,
    "GHI": 1,
    "GLO": 1,
    "OPL": 1,
    "PLO": 1,
    "PHI": 1,
    "DIV": 1,
    "MOD": 1,
    "AND": 1,
    "IAN": 1,
    "BOR": 1,
    "XOR": 1,
    "SGN": 1,
    "ADD": 1,
    "SUB": 1,
    "CAD": 1,
    "CSB": 1,
    "NEQ": 1,
    "EQU": 1,
    "LST": 1,
    "LSE": 1,
    "SHL": 1,
    "SHR": 1,
    "ROL": 1,
    "SAR": 1,
}


STATIC_OPERATION_COSTS = {
    # RSP helper occupancy measured/expected at the compiled OASM layer.
    # These costs intentionally do not change source-level AtomicMorphism
    # duration_cycles, which remain logical timestamps rather than instruction
    # occupancy.
    OperationType.RSP_RF_CONFIG: 13,
    OperationType.RSP_PID_CONFIG: 39,
}


def static_operation_cost(operation_type: OperationType) -> int:
    """Return a static compiled-instruction occupancy estimate in cycles."""
    return STATIC_OPERATION_COSTS.get(operation_type, 0)


def estimate_oasm_cost(assembly_lines: List[str]) -> int:
    """Calculate total execution cost for RTMQ assembly lines."""
    loop_info = analyze_loop_structure(assembly_lines)
    total_cost = 0
    instruction_history = []

    for i, line in enumerate(assembly_lines):
        parts = line.strip().split()
        if not parts:
            continue

        instruction = parts[0].upper()
        flag = parts[1].upper() if len(parts) > 1 else "-"
        target_reg = parts[2].upper() if len(parts) > 2 else ""
        cost = RTMQ_INSTRUCTION_COSTS.get(instruction, 1)

        if instruction in ["AMK", "CLO"] and target_reg == "PTR" and flag == "P":
            if i in loop_info.get("jump_instructions", []):
                total_cost += 10 * loop_info.get("estimated_iterations", 1)
            else:
                total_cost += 10
            instruction_history.append(("JUMP_PTR", target_reg, 0))
            continue

        loop_multiplier = (
            loop_info.get("estimated_iterations", 1)
            if i in loop_info.get("loop_body_instructions", [])
            else 1
        )
        total_cost += cost * loop_multiplier
        if flag == "P":
            total_cost += 6 * loop_multiplier

        gap_cycles = calculate_gap_cycles(instruction, target_reg, instruction_history)
        total_cost += gap_cycles * loop_multiplier

        instruction_history.append((instruction, target_reg, 0))
        if len(instruction_history) > 3:
            instruction_history.pop(0)

    return total_cost


def analyze_loop_structure(assembly_lines: List[str]) -> dict:
    """Analyze common loop structures in RTMQ assembly."""
    result = {
        "estimated_iterations": 1,
        "loop_body_instructions": [],
        "jump_instructions": [],
        "loop_type": "none",
    }
    if len(assembly_lines) < 5:
        return result

    jumps = []
    compare_instructions = []

    for i, line in enumerate(assembly_lines):
        parts = line.strip().split()
        if len(parts) < 3:
            continue
        instruction = parts[0].upper()
        flag = parts[1].upper() if len(parts) > 1 else "-"
        target_reg = parts[2].upper() if len(parts) > 2 else ""

        if instruction in ["AMK", "CLO"] and target_reg == "PTR" and flag == "P":
            jumps.append(i)
        if instruction in ["LSE", "LST", "EQU", "NEQ"]:
            compare_instructions.append((i, instruction, parts))

    if len(jumps) >= 2 and compare_instructions:
        for comp_idx, comp_instr, comp_parts in compare_instructions:
            if comp_instr == "LSE" and len(comp_parts) >= 4:
                try:
                    limit_value = int(comp_parts[3]) if comp_parts[3].isdigit() else 5
                    next_jumps = [j for j in jumps if j > comp_idx]
                    if next_jumps:
                        conditional_jump = next_jumps[0]
                        back_jump = jumps[-1]
                        result.update(
                            {
                                "estimated_iterations": limit_value + 1,
                                "loop_body_instructions": list(range(comp_idx, back_jump + 1)),
                                "jump_instructions": [conditional_jump, back_jump],
                                "loop_type": "for_loop",
                            }
                        )
                        break
                except (ValueError, IndexError):
                    continue
    return result


def calculate_gap_cycles(current_instr: str, current_target: str, history: List[tuple]) -> int:
    """Calculate gap cycles from recent instruction history."""
    if not history:
        return 0

    prev_instr, prev_target, _ = history[-1]

    if current_instr == "CSR" and prev_instr in ["CLO", "AMK"] and prev_target == current_target:
        return 3
    if current_instr == "CSR" and len(history) >= 2:
        for hist_instr, hist_target, _unused in reversed(history[-2:]):
            if hist_instr == "SFS":
                return 5
            if hist_instr in ["CLO", "AMK"] and is_subfile_register(hist_target):
                return 5
    if current_instr == "CSR" and prev_instr in ["GLO", "GHI"] and is_tcs_register(current_target):
        return 1
    if prev_instr in ["CLO", "AMK"] and prev_target == "STK":
        if is_tcs_write(current_instr):
            return 1
        if current_instr == "CSR" and is_tcs_register(current_target):
            return 4
    if current_instr in ["PHI", "PLO"] and prev_instr == "OPL":
        return 7
    if current_instr in ["DIV", "MOD"] and prev_instr == "OPL":
        return 35
    if current_instr == "CSR":
        if current_target == "DCD" and prev_instr in ["CLO", "AMK"] and prev_target == "DCA":
            return 9
        if current_target == "ICD" and prev_instr in ["CLO", "AMK"] and prev_target == "ICA":
            return 7
    return 0


def is_subfile_register(reg_name: str) -> bool:
    return reg_name in ["NEX", "SCP", "WCL", "WCH"]


def is_tcs_register(reg_name: str) -> bool:
    return reg_name.startswith("$")


def is_tcs_write(instr: str) -> bool:
    return instr in ["GLO", "GHI"]


def analyze_gap_for_instruction(instruction: str, target_reg: str, history: list[str]) -> int:
    """Calculate gap cycles for a single instruction given recent history."""
    if not history:
        return 0

    prev_instr = history[-1]
    prev_target = history[-2] if len(history) >= 2 else ""

    if instruction == "CSR" and prev_instr in ("CLO", "AMK") and prev_target == target_reg:
        return 3
    if instruction == "CSR" and len(history) >= 2:
        for hist_instr, hist_target in zip(reversed(history[-2:][::2]), reversed(history[-2:][1::2])):
            if hist_instr == "SFS":
                return 5
            if hist_instr in ("CLO", "AMK") and hist_target in ("NEX", "SCP", "WCL", "WCH"):
                return 5
    if instruction == "CSR" and prev_instr in ("GLO", "GHI") and target_reg.startswith("$"):
        return 1
    if prev_instr in ("CLO", "AMK") and prev_target == "STK":
        if instruction in ("GLO", "GHI"):
            return 1
        if instruction == "CSR" and target_reg.startswith("$"):
            return 4
    if instruction in ("PHI", "PLO") and prev_instr == "OPL":
        return 7
    if instruction in ("DIV", "MOD") and prev_instr == "OPL":
        return 35
    if instruction == "CSR":
        if target_reg == "DCD" and prev_instr in ("CLO", "AMK") and prev_target == "DCA":
            return 9
        if target_reg == "ICD" and prev_instr in ("CLO", "AMK") and prev_target == "ICA":
            return 7
    return 0


def _parse_line(line: str) -> tuple[str, str, str]:
    """Parse one disassembler line into (instruction, flag, target_reg)."""
    parts = line.strip().split()
    if not parts:
        return ("", "", "")
    instruction = parts[0].upper()
    flag = parts[1].upper() if len(parts) > 1 else "-"
    target_reg = parts[2].upper() if len(parts) > 2 else ""
    return (instruction, flag, target_reg)


def _instruction_cost(instruction: str, target_reg: str, flag: str, loop_mult: int = 1) -> int:
    """Base cost of one RTMQ instruction (no gap cycles)."""
    cost = RTMQ_INSTRUCTION_COSTS.get(instruction, 1)
    if instruction in ("AMK", "CLO") and target_reg == "PTR" and flag == "P":
        return 10 * loop_mult
    return cost * loop_mult + (6 * loop_mult if flag == "P" else 0)


def analyze_batch_costs(
    all_events: list,
    adr: OASMAddress,
    assembler_seq,
    verbose: bool = False,
) -> None:
    """Analyze costs for all events of one board in a single assemble/disassemble.

    Single-pass: accumulate every event's OASM calls, take cumulative snapshots,
    disassemble once, then assign instructions to events.

    Boards whose address is not backed by a node on ``assembler_seq`` are skipped
    silently; their events keep the static cost assigned by the caller. This
    mirrors the previous per-event implementation, which swallowed unsupported
    boards via its ``try/except`` fallback.
    """
    from .execution import OASM_FUNCTION_MAP

    # Collect events that have OASM calls, preserving order
    costed = [(i, ev) for i, ev in enumerate(all_events) if ev.oasm_calls]
    if not costed:
        return

    # The (adr, func, ...) calling convention only works on multi-node
    # assemblers, and only for nodes that were configured at construction.
    # Single-node assemblers (multi is None) interpret args[0] as the function
    # itself, so we cannot route by address; skip such boards entirely.
    multi = getattr(assembler_seq.asm, "multi", None)
    if multi is None or adr.value not in multi:
        if verbose:
            print(
                f"      Skipping cost analysis for {adr.value}: "
                f"not a configured assembler node."
            )
        return

    # Single-pass: accumulate calls, snapshot line count after each event
    assembler_seq.clear()
    cum_counts: list[int] = []
    for _idx, event in costed:
        for call in event.oasm_calls:
            func = OASM_FUNCTION_MAP.get(call.dsl_func)
            if func:
                if call.kwargs:
                    assembler_seq(call.adr.value, func, *call.args, **call.kwargs)
                else:
                    assembler_seq(call.adr.value, func, *call.args)
        if adr.value in assembler_seq.asm.multi:
            cum_counts.append(len(assembler_seq.asm[adr.value]))
        else:
            cum_counts.append(0)

    # Single final disassemble
    if adr.value not in assembler_seq.asm.multi:
        return
    asm_lines = disassembler(core=C_RWG)(assembler_seq.asm[adr.value])
    total_lines = len(asm_lines)

    # Analyze loop structure once on the full assembly
    loop_info = analyze_loop_structure(asm_lines)
    loop_body_set = set(loop_info.get("loop_body_instructions", []))
    jump_set = set(loop_info.get("jump_instructions", []))
    est_iter = loop_info.get("estimated_iterations", 1)

    # Assign each line to an event
    n_events = len(costed)
    line_of_event = [0] * total_lines
    ev = 0
    for li in range(total_lines):
        while ev + 1 < n_events and li >= cum_counts[ev]:
            ev += 1
        line_of_event[li] = ev

    # Compute per-event cost preserving cross-boundary gap cycles
    tail_history: list[str] = []
    for li in range(total_lines):
        ev = line_of_event[li]
        instruction, flag, target_reg = _parse_line(asm_lines[li])
        if not instruction:
            continue

        loop_mult = est_iter if li in loop_body_set else 1
        if li in jump_set and instruction in ("AMK", "CLO") and target_reg == "PTR" and flag == "P":
            loop_mult = est_iter

        costed[ev][1].cost_cycles += _instruction_cost(instruction, target_reg, flag, loop_mult)

        gap = analyze_gap_for_instruction(instruction, target_reg, tail_history)
        costed[ev][1].cost_cycles += gap * loop_mult

        tail_history.append(target_reg)
        tail_history.append(instruction)
        if len(tail_history) > 6:
            tail_history = tail_history[-6:]


def analyze_operation_cost(event, adr: OASMAddress, assembler_seq, verbose: bool = False) -> int:
    """Estimate execution cost for one logical event.

    .. deprecated::
       Prefer analyze_batch_costs() for bulk analysis. This per-event
       function is retained for backward compatibility and debugging.
    """
    try:
        assembler_seq.clear()
        for call in event.oasm_calls:
            func = OASM_FUNCTION_MAP.get(call.dsl_func)
            if func:
                if call.kwargs:
                    assembler_seq(call.adr.value, func, *call.args, **call.kwargs)
                else:
                    assembler_seq(call.adr.value, func, *call.args)

        if adr.value in assembler_seq.asm.multi:
            binary_asm = assembler_seq.asm[adr.value]
            asm_lines = disassembler(core=C_RWG)(binary_asm)
            return estimate_oasm_cost(asm_lines)
        return 0
    except Exception as e:
        if verbose:
            print(f"      Warning: Cost analysis failed for {event.operation.operation_type.name}: {e}")
        return 0
