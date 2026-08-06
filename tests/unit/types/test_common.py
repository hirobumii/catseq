"""Unit tests for the host-visible source-language value types."""

import pytest

from catseq.types.common import Board, Channel, ChannelType


def test_channel_type_members_are_distinct() -> None:
    members = {ChannelType.TTL, ChannelType.RWG, ChannelType.RSP}
    assert len(members) == 3


class TestBoard:
    def test_str_returns_id(self) -> None:
        assert str(Board("rwg0")) == "rwg0"

    def test_is_frozen(self) -> None:
        board = Board("rwg0")
        with pytest.raises(AttributeError):
            board.id = "other"  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        assert Board("rwg0") == Board("rwg0")
        assert Board("rwg0") != Board("rwg1")


class TestChannel:
    def test_global_id_combines_board_type_and_local_id(self) -> None:
        channel = Channel(Board("rwg0"), local_id=3, channel_type=ChannelType.TTL)
        assert channel.global_id == "rwg0_TTL_3"

    def test_str_returns_global_id(self) -> None:
        channel = Channel(Board("rwg0"), local_id=0, channel_type=ChannelType.RWG)
        assert str(channel) == "rwg0_RWG_0"

    def test_zero_local_id_is_allowed(self) -> None:
        channel = Channel(Board("rwg0"), local_id=0, channel_type=ChannelType.RSP)
        assert channel.local_id == 0

    def test_negative_local_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            Channel(Board("rwg0"), local_id=-1, channel_type=ChannelType.TTL)

    def test_equality_by_value(self) -> None:
        board = Board("rwg0")
        first = Channel(board, local_id=1, channel_type=ChannelType.TTL)
        second = Channel(board, local_id=1, channel_type=ChannelType.TTL)
        assert first == second
