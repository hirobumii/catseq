from catseq.time_utils import us
from catseq.types.common import Board, Channel, ChannelType, OperationType
from catseq.types.ttl import TTLState
from catseq.v2 import hold
from catseq.v2 import ttl as ttl_v2


def test_ttl_pulse_materializes_on_concrete_channel():
    ch = Channel(Board("rwg0"), 0, ChannelType.TTL)

    morphism = ttl_v2.on() >> hold(10 * us) >> ttl_v2.off()
    legacy, end_states = morphism.on(ch).materialize_with_states(TTLState.OFF)

    ops = legacy.lanes[ch].operations
    assert [op.operation_type for op in ops] == [
        OperationType.TTL_ON,
        OperationType.IDENTITY,
        OperationType.TTL_OFF,
    ]
    assert ops[1].duration_cycles > 0
    assert end_states[ch] == TTLState.OFF


def test_parallel_v2_morphism_materializes_without_recursion_sensitive_surface():
    ch0 = Channel(Board("rwg0"), 0, ChannelType.TTL)
    ch1 = Channel(Board("rwg0"), 1, ChannelType.TTL)

    left = (ttl_v2.initialize() >> ttl_v2.on()).on(ch0)
    right = (ttl_v2.initialize() >> ttl_v2.on()).on(ch1)

    legacy = (left | right).materialize({
        ch0: TTLState.UNINITIALIZED,
        ch1: TTLState.UNINITIALIZED,
    })

    assert set(legacy.lanes.keys()) == {ch0, ch1}
