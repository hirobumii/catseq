import pytest


pytest.importorskip("oasm")

from catseq.v2.compiler import compile_v2_morphism_to_oasm_calls
from catseq.compilation.types import OASMFunction


def test_v2_reference_experiment_compiles_to_multiboard_oasm(v2_reference_context):
    calls_by_board = compile_v2_morphism_to_oasm_calls(
        v2_reference_context.build(),
        v2_reference_context.start_states(),
    )

    assert {address.value for address in calls_by_board} == {"main", "rwg0", "rwg1", "rwg2", "rwg4", "rwg5"}

    funcs_by_board = {
        address.value: {call.dsl_func for call in calls}
        for address, calls in calls_by_board.items()
    }

    assert OASMFunction.TTL_CONFIG in funcs_by_board["main"]
    assert OASMFunction.TTL_SET in funcs_by_board["main"]
    assert OASMFunction.RWG_PLAY in funcs_by_board["rwg0"]
    assert OASMFunction.RWG_PLAY in funcs_by_board["rwg1"]
    assert OASMFunction.RWG_PLAY in funcs_by_board["rwg4"]
    assert OASMFunction.RWG_RF_SWITCH in funcs_by_board["rwg5"]
    assert OASMFunction.TTL_SET in funcs_by_board["rwg2"]
