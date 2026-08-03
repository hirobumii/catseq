from catseq.targets import rtmq_v2_profile


def test_builtin_target_profile_does_not_name_downstream_systems():
    operations = rtmq_v2_profile()["operations"]

    assert not any(name.startswith("rb1system.") for name in operations)
