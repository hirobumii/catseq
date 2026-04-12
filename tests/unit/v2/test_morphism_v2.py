from catseq.time_utils import us
from catseq.v2.compiler import lower_v2_morphism_to_schedule
from catseq.types.common import Board, Channel, ChannelType, OperationType
from catseq.types.ttl import TTLState
from catseq.v2.hardware import ttl as ttl_v2
from catseq.v2.morphism import hold


def test_ttl_pulse_materializes_on_concrete_channel():
    ch = Channel(Board("rwg0"), 0, ChannelType.TTL)

    morphism = ttl_v2.on() >> hold(10 * us) >> ttl_v2.off()
    realized, end_states = morphism.on(ch).materialize_with_states(TTLState.OFF)

    ops = realized.timed_operations()
    assert [timed.operation.operation_type for timed in ops] == [
        OperationType.TTL_ON,
        OperationType.IDENTITY,
        OperationType.TTL_OFF,
    ]
    assert ops[1].operation.duration_cycles > 0
    assert end_states[ch] == TTLState.OFF


def test_parallel_v2_morphism_materializes_without_recursion_sensitive_surface():
    ch0 = Channel(Board("rwg0"), 0, ChannelType.TTL)
    ch1 = Channel(Board("rwg0"), 1, ChannelType.TTL)

    left = (ttl_v2.initialize() >> ttl_v2.on()).on(ch0)
    right = (ttl_v2.initialize() >> ttl_v2.on()).on(ch1)

    realized = (left | right).materialize({
        ch0: TTLState.UNINITIALIZED,
        ch1: TTLState.UNINITIALIZED,
    })

    assert {timed.operation.channel for timed in realized.timed_operations()} == {ch0, ch1}


def test_simple_v2_schedule_dump_is_reviewable():
    ch = Channel(Board("rwg0"), 0, ChannelType.TTL)
    morphism = (ttl_v2.on() >> hold(10 * us) >> ttl_v2.off()).on(ch)

    schedule = lower_v2_morphism_to_schedule(morphism, TTLState.OFF)
    dumped = schedule.dump()

    assert dumped["root"] == 5
    assert dumped["nodes"][1]["kind"] == "timed_op"
    assert dumped["nodes"][1]["operation"]["operation_type"] == "IDENTITY"
    assert "start_cycles" not in dumped["nodes"][1]
    assert dumped["nodes"][1]["duration_cycles"] > 0
    assert dumped["nodes"][2]["kind"] == "timed_op"
    assert dumped["nodes"][2]["operation"]["operation_type"] == "TTL_ON"
    assert dumped["nodes"][3]["operation"]["operation_type"] == "TTL_OFF"
    assert dumped["nodes"][4] == {"kind": "board_region", "children": (1, 2, 3), "board": "rwg0"}
    assert dumped["nodes"][5] == {"kind": "root", "children": (4,)}
