from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path

import pytest

from catseq.time_utils import us
from catseq.types.common import Board, Channel, ChannelType, OperationType
from catseq.types.rwg import RWGReady, RWGUninitialized, StaticWaveform
from catseq.v2 import rwg as rwg_v2
from catseq.v2 import (
    BitMatrix,
    BitVec,
    Branch,
    Call,
    Emit,
    ForRange,
    FunctionDef,
    Let,
    Measure,
    Program,
    Return,
    var,
)


@dataclass(frozen=True)
class _AxisStep:
    starts: tuple[int, ...]
    ends: tuple[int, ...]


def _ordered_pair(starts: tuple[int, ...], ends: tuple[int, ...]) -> _AxisStep:
    moved_starts: list[int] = []
    moved_ends: list[int] = []
    for start, end in zip(starts, ends, strict=True):
        if start != end:
            moved_starts.append(start)
            moved_ends.append(end)
    return _AxisStep(tuple(moved_starts), tuple(moved_ends))


def _pair_with_priority(
    loading: BitVec,
    target: BitVec,
    priority: list[int] | tuple[int, ...] | None = None,
) -> tuple[_AxisStep, BitVec]:
    if len(loading) != len(target):
        raise ValueError("loading and target width mismatch")
    if priority is None:
        priority = [0] * len(target)
    loading_positions = list(loading.iter_ones())
    target_positions = list(target.iter_ones())
    ordered_targets = sorted(target_positions, key=lambda index: (priority[index], index))
    pair_count = min(len(loading_positions), len(ordered_targets))
    final_targets = sorted(ordered_targets[:pair_count])
    step = _ordered_pair(tuple(loading_positions[:pair_count]), tuple(final_targets))

    after = loading
    target_bits = BitVec.zeros(len(loading))
    for start, end in zip(step.starts, step.ends, strict=True):
        after = after.with_bit(start, 0)
        target_bits = target_bits.with_bit(end, 1)
    return step, after | target_bits


def _tetris_plan(loadings: BitMatrix, targets: BitMatrix) -> dict[str, object]:
    if loadings.nr != targets.nr or loadings.nc != targets.nc:
        raise ValueError("shape mismatch")

    priorities: list[list[int]] = [[] for _ in range(targets.nc)]
    for row_index, row in enumerate(targets.iter_rows()):
        for col_index in row.iter_ones():
            priorities[col_index].append(row_index)

    row_steps: list[_AxisStep] = []
    current_rows: list[BitVec] = []
    success = True

    for row_index in range(loadings.nr):
        row_target = [0] * loadings.nc
        row_priority = []
        for col_index, queue in enumerate(priorities):
            row_priority.append(queue[0] if queue else loadings.nr + 100)
            if queue:
                row_target[col_index] = 1
        step, final_row = _pair_with_priority(
            loadings.row(row_index),
            BitVec(tuple(row_target)),
            row_priority,
        )
        for col_index in final_row.iter_ones():
            if priorities[col_index]:
                priorities[col_index] = priorities[col_index][1:]
        row_steps.append(step)
        current_rows.append(final_row)

    for queue in priorities:
        if queue:
            success = False

    intermediate = BitMatrix.from_rows(tuple(current_rows))
    col_steps: list[_AxisStep] = []
    final_cols: list[BitVec] = []
    for current_col, target_col in zip(intermediate.iter_cols(), targets.iter_cols(), strict=True):
        step, final_col = _pair_with_priority(current_col, target_col)
        col_steps.append(step)
        final_cols.append(final_col)
    final = BitMatrix.from_cols(tuple(final_cols))

    return {
        "success": success,
        "row_steps": tuple(row_steps),
        "col_steps": tuple(col_steps),
        "intermediate": intermediate,
        "final": final,
    }


def _load_rb1_tetris():
    module_path = Path("/home/tosaka/Rb1-rtmq/analysis/rearrangement.py")
    if not module_path.exists():
        pytest.skip("Rb1-rtmq reference repo is not available.")
    spec = importlib.util.spec_from_file_location("rb1_rearrangement", module_path)
    if spec is None or spec.loader is None:
        pytest.skip("Failed to create import spec for Rb1-rtmq rearrangement module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_program_function_loop_and_return():
    program = Program(
        FunctionDef(
            "double",
            ("x",),
            Program(Return(var("x") * 2)),
        ),
        Let("total", 0),
        ForRange(
            "i",
            0,
            4,
            Program(
                Let("term", Call("double", (var("i"),))),
                Let("total", var("total") + var("term")),
            ),
        ),
    )

    result = program.run()

    assert result.env["total"] == 12


def test_program_measure_branch_and_dynamic_emit_materializes_runtime_values():
    channel = Channel(Board("rwg0"), 0, ChannelType.RWG)
    program = Program(
        Measure("carrier_freq"),
        Branch(
            var("carrier_freq") > 100.0,
            Program(Emit(rwg_v2.initialize(var("carrier_freq")).on(channel))),
            Program(Emit(rwg_v2.initialize(80.0).on(channel))),
        ),
    )

    result = program.run(
        start_states={channel: RWGUninitialized()},
        measurements={"carrier_freq": 123.0},
    )

    ops = result.morphism.lanes[channel].operations
    assert [op.operation_type for op in ops] == [
        OperationType.RWG_INIT,
        OperationType.RWG_SET_CARRIER,
    ]
    assert isinstance(result.end_states[channel], RWGReady)
    assert result.end_states[channel].carrier_freq == pytest.approx(123.0)


def test_program_ast_can_express_measure_plan_branch_reference_flow():
    targets = BitMatrix.from_nested_lists(
        [
            [0, 1, 0, 1],
            [1, 0, 1, 0],
            [0, 1, 1, 0],
        ]
    )
    measured = BitMatrix.from_nested_lists(
        [
            [1, 0, 0, 1],
            [1, 1, 0, 0],
            [0, 0, 1, 1],
        ]
    )

    program = Program(
        Measure("occupancy"),
        Let("plan", Call("tetris_plan", (var("occupancy"), var("targets")))),
        Branch(
            var("plan")["success"],
            Program(Let("final_layout", var("plan")["final"])),
            Program(Let("final_layout", var("occupancy"))),
        ),
    )

    result = program.run(
        measurements={"occupancy": measured},
        runtime_env={"targets": targets},
        functions={"tetris_plan": _tetris_plan},
    )

    plan = result.env["plan"]
    assert plan["success"] is True
    assert isinstance(plan["intermediate"], BitMatrix)
    assert result.env["final_layout"] == targets


def test_reference_tetris_matches_rb1_reference_when_available():
    rb1 = _load_rb1_tetris()

    loadings = BitMatrix.from_nested_lists(
        [
            [1, 0, 0, 1],
            [1, 1, 0, 0],
            [0, 0, 1, 1],
        ]
    )
    targets = BitMatrix.from_nested_lists(
        [
            [0, 1, 0, 1],
            [1, 0, 1, 0],
            [0, 1, 1, 0],
        ]
    )

    expected = _tetris_plan(loadings, targets)
    success, row_steps, col_steps, final = rb1.tetris(
        rb1.AtomArray(loadings.to_list()),
        rb1.AtomArray(targets.to_list()),
        verbose=False,
    )

    assert expected["success"] is success
    assert tuple((tuple(step.starts), tuple(step.ends)) for step in expected["row_steps"]) == tuple(
        (tuple(starts), tuple(ends)) for starts, ends in row_steps
    )
    assert tuple((tuple(step.starts), tuple(step.ends)) for step in expected["col_steps"]) == tuple(
        (tuple(starts), tuple(ends)) for starts, ends in col_steps
    )
    assert expected["final"].to_list() == final.to_list()


def test_runtime_emit_supports_symbolic_waveform_fields_inside_program():
    channel = Channel(Board("rwg0"), 0, ChannelType.RWG)
    program = Program(
        Emit(rwg_v2.initialize(100.0).on(channel)),
        Let("next_freq", 8.75),
        Emit(
            (
                rwg_v2.set_state(
                    [
                        StaticWaveform(
                            sbg_id=0,
                            freq=var("next_freq"),
                            amp=0.1,
                            phase=0.0,
                            fct=0,
                        )
                    ]
                )
                >> rwg_v2.rf_pulse(5 * us)
            ).on(channel)
        ),
    )

    result = program.run(start_states={channel: RWGUninitialized()})

    assert result.end_states[channel].snapshot[0].freq == pytest.approx(8.75)
