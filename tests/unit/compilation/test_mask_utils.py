"""Unit tests for the pure-Python RTMQ mask conversion helpers."""

import pytest

from catseq.compilation.mask_utils import (
    binary_to_rtmq_mask,
    encode_rtmq_mask,
    rtmq_mask_to_binary,
    smart_mask_convert,
)


class TestBinaryToRtmqMask:
    def test_zero_maps_to_zero_group(self) -> None:
        assert binary_to_rtmq_mask(0) == "0.0"

    @pytest.mark.parametrize(
        "binary, expected",
        [
            (0b0001, "1.0"),
            (0b0011, "3.0"),
            (0b0111, "7.0"),
            (0b1111, "F.0"),
            (0b1100, "C.0"),
        ],
    )
    def test_low_four_bits_use_group_zero(self, binary: int, expected: str) -> None:
        assert binary_to_rtmq_mask(binary) == expected

    @pytest.mark.parametrize(
        "binary, expected",
        [
            (1 << 4, "1.2"),
            (1 << 8, "1.4"),
            (1 << 10, "1.5"),
            (0xF << 8, "F.4"),
        ],
    )
    def test_higher_bits_pick_smallest_pattern(
        self, binary: int, expected: str
    ) -> None:
        assert binary_to_rtmq_mask(binary) == expected

    def test_unrepresentable_mask_returns_original_int(self) -> None:
        # 0b10001: bit 0 forces group 0, but the value exceeds a nibble.
        assert binary_to_rtmq_mask(0b10001) == 0b10001


class TestRtmqMaskToBinary:
    @pytest.mark.parametrize(
        "rtmq, expected",
        [
            ("1.0", 1),
            ("1.1", 4),
            ("3.0", 3),
            ("F.2", 240),
            ("0.0", 0),
        ],
    )
    def test_decodes_known_values(self, rtmq: str, expected: int) -> None:
        assert rtmq_mask_to_binary(rtmq) == expected

    def test_missing_separator_raises(self) -> None:
        with pytest.raises(ValueError, match="Expected 'A.B' format"):
            rtmq_mask_to_binary("11")


class TestEncodeRtmqMask:
    @pytest.mark.parametrize(
        "rtmq, expected",
        [
            ("3.1", (3 << 4) + 1),
            ("F.2", (15 << 4) + 2),
            ("0.0", 0),
        ],
    )
    def test_encodes_known_values(self, rtmq: str, expected: int) -> None:
        assert encode_rtmq_mask(rtmq) == expected

    def test_missing_separator_raises(self) -> None:
        with pytest.raises(ValueError, match="Expected 'A.B' format"):
            encode_rtmq_mask("31")

    def test_out_of_range_digits_raise(self) -> None:
        with pytest.raises(ValueError, match="single hex digits"):
            encode_rtmq_mask("1F.0")


class TestSmartMaskConvert:
    def test_zero_maps_to_zero_group(self) -> None:
        assert smart_mask_convert(0) == "0.0"

    @pytest.mark.parametrize(
        "binary, expected",
        [
            (0b0001, "1.0"),
            (1 << 2, "1.1"),
            (0b0011, "3.0"),
            (0b0101, "5.0"),
        ],
    )
    def test_converts_representable_masks(
        self, binary: int, expected: str
    ) -> None:
        assert smart_mask_convert(binary) == expected

    def test_unrepresentable_mask_returns_original_int(self) -> None:
        assert smart_mask_convert(0b10001) == 0b10001


@pytest.mark.parametrize("binary", list(range(1, 16)))
def test_binary_to_rtmq_round_trips_for_low_nibble(binary: int) -> None:
    rtmq = binary_to_rtmq_mask(binary)
    assert isinstance(rtmq, str)
    assert rtmq_mask_to_binary(rtmq) == binary


@pytest.mark.parametrize("bit", [0, 2, 4, 6, 8, 10])
def test_single_even_bit_round_trips(bit: int) -> None:
    binary = 1 << bit
    rtmq = binary_to_rtmq_mask(binary)
    assert isinstance(rtmq, str)
    assert rtmq_mask_to_binary(rtmq) == binary
