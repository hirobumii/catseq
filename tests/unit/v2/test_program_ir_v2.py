from __future__ import annotations

import pytest

from catseq.v2.compiler import ProgramLoweringError, lower_program_to_ir, prepare_morphism_region
from catseq.types.common import Board, Channel, ChannelType, OperationType
from catseq.types.rwg import RWGReady, RWGUninitialized
from catseq.types.ttl import TTLState
from catseq.v2 import input_state, var
from catseq.v2.hardware import rwg as rwg_v2
from catseq.v2.hardware import ttl as ttl_v2
from catseq.v2.morphism import Morphism
from catseq.v2.program import Branch, Emit, Let, Measure, Program, Select, While


def test_prepare_region_resolves_state_only_fields_and_preserves_runtime_vars():
    channel = Channel(Board("rwg0"), 0, ChannelType.RWG)
    morphism = Morphism.atomic(
        OperationType.IDENTITY,
        channel=channel,
        state_requirement=RWGReady,
        end_state_factory=lambda state: RWGReady(carrier_freq=input_state().carrier_freq + var("delta")),
    )

    prepared = prepare_morphism_region(morphism, {channel: RWGReady(100.0)})
    dumped = prepared.dump()

    assert prepared.free_vars == frozenset({"delta"})
    timed_op = dumped["nodes"][1]
    assert timed_op["operation"]["operation_type"] == "IDENTITY"
    assert timed_op["operation"]["end_state"]["fields"]["carrier_freq"]["sym"] == "add"
    assert timed_op["operation"]["end_state"]["fields"]["carrier_freq"]["args"][0]["sym"] == "const"
    assert timed_op["operation"]["end_state"]["fields"]["carrier_freq"]["args"][0]["value"] == 100.0
    assert timed_op["operation"]["end_state"]["fields"]["carrier_freq"]["args"][1]["sym"] == "var"


def test_lower_program_to_ir_builds_control_and_region_arenas():
    ttl_channel = Channel(Board("main"), 0, ChannelType.TTL)
    rwg_channel = Channel(Board("rwg0"), 0, ChannelType.RWG)
    keep_region = ttl_v2.on().on(ttl_channel)
    drive_region = rwg_v2.initialize(var("carrier_freq")).on(rwg_channel)

    program = Program(
        Measure("keep"),
        Let("carrier_freq", Select(var("keep"), 120.0, 95.0)),
        Branch(
            var("keep"),
            Program(Emit(keep_region), Emit(drive_region)),
            Program(Emit(ttl_v2.off().on(ttl_channel))),
        ),
    )

    lowered = lower_program_to_ir(
        program,
        start_states={
            ttl_channel: TTLState.OFF,
            rwg_channel: RWGUninitialized(),
        },
    )
    dumped = lowered.dump()

    control_nodes = dumped["control"]["nodes"]
    assert dumped["root_block"] in control_nodes
    assign_nodes = [node for node in control_nodes.values() if node["kind"] == "assign"]
    assert len(assign_nodes) == 1
    assert assign_nodes[0]["value"]["select"]["then"] == 120.0
    branch_nodes = [node for node in control_nodes.values() if node["kind"] == "branch"]
    assert len(branch_nodes) == 1
    assert "then_block" in branch_nodes[0]
    assert "else_block" in branch_nodes[0]
    region_nodes = dumped["regions"]["nodes"]
    region_roots = [node_id for node_id, node in region_nodes.items() if node["kind"] == "region_root"]
    assert len(region_roots) == 3
    assert any(node.get("free_vars") == ("carrier_freq",) for node in region_nodes.values())


def test_lower_program_rejects_loops_for_now():
    with pytest.raises(ProgramLoweringError):
        lower_program_to_ir(
            Program(
                Let("x", 0),
                While(var("x"), Program(Let("x", 1))),
            )
        )


def test_lower_program_rejects_non_terminal_branch():
    channel = Channel(Board("main"), 0, ChannelType.TTL)
    program = Program(
        Branch(
            var("keep"),
            Program(Emit(ttl_v2.on().on(channel))),
            Program(Emit(ttl_v2.off().on(channel))),
        ),
        Let("later", 1),
    )

    with pytest.raises(ProgramLoweringError):
        lower_program_to_ir(program, start_states={channel: TTLState.OFF})


def test_prepare_region_handles_real_rwg_region_with_runtime_freq():
    channel = Channel(Board("rwg0"), 0, ChannelType.RWG)
    region = rwg_v2.initialize(var("carrier_freq")).on(channel)

    prepared = prepare_morphism_region(region, {channel: RWGUninitialized()})
    dumped = prepared.dump()

    assert prepared.free_vars == frozenset({"carrier_freq"})
    timed_op = dumped["nodes"][1]
    assert timed_op["operation"]["operation_type"] == "RWG_INIT"
    set_carrier = dumped["nodes"][2]
    assert set_carrier["operation"]["operation_type"] == "RWG_SET_CARRIER"
    assert set_carrier["operation"]["end_state"]["fields"]["carrier_freq"]["sym"] == "var"
