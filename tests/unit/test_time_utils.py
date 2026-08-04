from decimal import Decimal

import pytest

import catseq.time_utils as time_utils


def test_time_conversion_requires_the_selected_target_clock() -> None:
    with pytest.raises(TypeError, match="clock_hz"):
        time_utils.time_to_cycles(1e-6)  # type: ignore[call-arg]

    assert time_utils.time_to_cycles(1e-6, clock_hz=100_000_000) == 100
    assert time_utils.cycles_to_time(100, clock_hz=100_000_000) == 1e-6


def test_time_conversion_accepts_decimal_inputs_without_rounding() -> None:
    assert (
        time_utils.time_to_cycles(
            Decimal("0.000001"), clock_hz=100_000_000
        )
        == 100
    )

    with pytest.raises(ValueError, match="non-integral target Cycle Delta"):
        time_utils.time_to_cycles(
            Decimal("0.000000015"), clock_hz=100_000_000
        )


def test_time_conversion_preserves_signed_logical_displacements() -> None:
    assert time_utils.time_to_cycles(-20e-9, clock_hz=100_000_000) == -2
    assert time_utils.cycles_to_time(-2, clock_hz=100_000_000) == -20e-9

    with pytest.raises(ValueError, match="non-integral target Cycle Delta"):
        time_utils.time_to_cycles(
            Decimal("-0.000000015"), clock_hz=100_000_000
        )


def test_legacy_implicit_clock_aliases_are_not_public() -> None:
    for name in ("CLOCK_FREQ_HZ", "CYCLE_DURATION_S", "CYCLES_PER_US", "mu"):
        assert not hasattr(time_utils, name)
