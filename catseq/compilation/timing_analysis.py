"""
RTMQ timing and cost-analysis helpers.
"""

from typing import List

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


def analyze_operation_cost(event, adr: OASMAddress, assembler_seq, verbose: bool = False) -> int:
    """Estimate execution cost for one logical event."""
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
