from catseq.types.rwg import RWGActive
from catseq.types.ttl import TTLState


def test_v2_reference_experiment_materializes_as_realistic_multiboard_sequence(v2_reference_context):
    experiment = v2_reference_context.build()

    realized, end_states = experiment.materialize_with_states(v2_reference_context.start_states())
    timed_ops = realized.timed_operations()

    assert {timed.operation.channel for timed in timed_ops} == set(v2_reference_context.all_channels)
    assert realized.total_duration_us > 200_000
    assert {timed.operation.channel.board.id for timed in timed_ops} == {"main", "rwg0", "rwg1", "rwg2", "rwg4", "rwg5"}
    assert end_states[v2_reference_context.artiq_trig] == TTLState.OFF
    assert end_states[v2_reference_context.raman_sw] == TTLState.OFF
    assert isinstance(end_states[v2_reference_context.global_imaging], RWGActive)
    assert end_states[v2_reference_context.global_imaging].snapshot[0].amp == 0.12
