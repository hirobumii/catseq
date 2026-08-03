from __future__ import annotations

import pytest

from catseq.compilation.mask_utils import (
    binary_to_rtmq_mask,
    encode_rtmq_mask,
    rtmq_mask_to_binary,
    smart_mask_convert,
)


@pytest.mark.parametrize(
    ("binary", "expected"),
    [
        (0, "0.0"),
        (0b0001, "1.0"),
        (0b1100, "C.0"),
        (0b110000, "3.2"),
        (0xF << 8, "F.4"),
    ],
)
def test_binary_to_rtmq_mask_encodes_representable_masks(
    binary: int, expected: str
) -> None:
    assert binary_to_rtmq_mask(binary) == expected


@pytest.mark.parametrize("binary", [0b100010, 0b11111, 0b1_0000_0001])
def test_binary_to_rtmq_mask_rejects_unrepresentable_masks(binary: int) -> None:
    with pytest.raises(ValueError, match="cannot be represented"):
        binary_to_rtmq_mask(binary)


def test_binary_to_rtmq_mask_rejects_negative_masks() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        binary_to_rtmq_mask(-1)


def test_smart_mask_convert_rejects_unrepresentable_masks() -> None:
    with pytest.raises(ValueError, match="no exact RTMQ"):
        smart_mask_convert(0b100010)


@pytest.mark.parametrize("mask", ["", "1", "X.0", "1.Z", "1."])
def test_rtmq_mask_parsing_reports_invalid_formats(mask: str) -> None:
    with pytest.raises(ValueError, match="Invalid RTMQ mask format"):
        rtmq_mask_to_binary(mask)
    with pytest.raises(ValueError, match="Invalid RTMQ mask format"):
        encode_rtmq_mask(mask)


def test_rtmq_mask_round_trip() -> None:
    assert rtmq_mask_to_binary(binary_to_rtmq_mask(0b110000)) == 0b110000
    assert encode_rtmq_mask("F.2") == 242
