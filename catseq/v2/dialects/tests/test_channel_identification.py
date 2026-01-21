"""Test channel identification and board/channel distinction."""

import pytest
from catseq.v2.dialects.catseq_dialect import (
    ChannelType,
    AtomicOp,
    TensorOp,
)


class TestChannelIdentification:
    """Test that channels can distinguish different boards and channels."""

    def test_same_board_different_channels(self):
        """Test distinguishing different channels on the same board."""
        # RWG板0上的TTL通道0
        ch0 = ChannelType("rwg", 0, 0, "ttl")

        # RWG板0上的TTL通道1 (同一板卡，不同通道)
        ch1 = ChannelType("rwg", 0, 1, "ttl")

        # 应该不相等
        assert ch0 != ch1

        # 全局ID应该不同
        assert ch0.get_global_id() == "RWG_0_TTL_0"
        assert ch1.get_global_id() == "RWG_0_TTL_1"

        print(f"✓ Same board, different channels:")
        print(f"  Channel 0: {ch0.get_global_id()}")
        print(f"  Channel 1: {ch1.get_global_id()}")

    def test_different_boards_same_channel_num(self):
        """Test distinguishing same channel number on different boards."""
        # RWG板0上的TTL通道0
        ch_board0 = ChannelType("rwg", 0, 0, "ttl")

        # RWG板1上的TTL通道0 (不同板卡，相同通道号)
        ch_board1 = ChannelType("rwg", 1, 0, "ttl")

        # 应该不相等
        assert ch_board0 != ch_board1

        # 全局ID应该不同
        assert ch_board0.get_global_id() == "RWG_0_TTL_0"
        assert ch_board1.get_global_id() == "RWG_1_TTL_0"

        print(f"\n✓ Different boards, same channel number:")
        print(f"  Board 0: {ch_board0.get_global_id()}")
        print(f"  Board 1: {ch_board1.get_global_id()}")

    def test_different_board_types(self):
        """Test distinguishing different board types."""
        # RWG板卡的通道0
        ch_rwg = ChannelType("rwg", 0, 0, "ttl")

        # MAIN板卡的通道0
        ch_main = ChannelType("main", 0, 0, "ttl")

        # RSP板卡的通道0
        ch_rsp = ChannelType("rsp", 0, 0, "ttl")

        # 三者应该都不相等
        assert ch_rwg != ch_main
        assert ch_rwg != ch_rsp
        assert ch_main != ch_rsp

        # 全局ID应该不同
        assert ch_rwg.get_global_id() == "RWG_0_TTL_0"
        assert ch_main.get_global_id() == "MAIN_0_TTL_0"
        assert ch_rsp.get_global_id() == "RSP_0_TTL_0"

        print(f"\n✓ Different board types:")
        print(f"  RWG board:  {ch_rwg.get_global_id()}")
        print(f"  MAIN board: {ch_main.get_global_id()}")
        print(f"  RSP board:  {ch_rsp.get_global_id()}")

    def test_different_channel_types_same_board(self):
        """Test distinguishing different channel types on same board."""
        # RWG板0上的TTL通道
        ch_ttl = ChannelType("rwg", 0, 0, "ttl")

        # RWG板0上的RWG通道 (同一板卡，不同通道类型)
        ch_rwg = ChannelType("rwg", 0, 0, "rwg")

        # 应该不相等
        assert ch_ttl != ch_rwg

        # 全局ID应该不同
        assert ch_ttl.get_global_id() == "RWG_0_TTL_0"
        assert ch_rwg.get_global_id() == "RWG_0_RWG_0"

        print(f"\n✓ Same board, different channel types:")
        print(f"  TTL channel: {ch_ttl.get_global_id()}")
        print(f"  RWG channel: {ch_rwg.get_global_id()}")

    def test_channel_equality_all_components(self):
        """Test that channel equality requires all 4 components to match."""
        # 基准通道: RWG板0, TTL通道0
        ch_base = ChannelType("rwg", 0, 0, "ttl")

        # 只有完全相同才相等
        ch_same = ChannelType("rwg", 0, 0, "ttl")
        assert ch_base == ch_same

        # 任何一个组件不同都不相等
        ch_diff_board_type = ChannelType("main", 0, 0, "ttl")  # 不同板卡类型
        ch_diff_board_id = ChannelType("rwg", 1, 0, "ttl")    # 不同板卡编号
        ch_diff_local_id = ChannelType("rwg", 0, 1, "ttl")    # 不同通道编号
        ch_diff_chan_type = ChannelType("rwg", 0, 0, "rwg")   # 不同通道类型

        assert ch_base != ch_diff_board_type
        assert ch_base != ch_diff_board_id
        assert ch_base != ch_diff_local_id
        assert ch_base != ch_diff_chan_type

        print(f"\n✓ Channel equality requires all 4 components to match")

    def test_multi_board_parallel_operations(self):
        """Test parallel operations across multiple boards."""
        # 3个不同板卡的通道
        ch_rwg0 = ChannelType("rwg", 0, 0, "ttl")   # RWG板0
        ch_rwg1 = ChannelType("rwg", 1, 0, "ttl")   # RWG板1
        ch_main = ChannelType("main", 0, 0, "ttl")  # MAIN板

        # 创建操作
        op_rwg0 = AtomicOp(op_name="pulse", channel=ch_rwg0, duration=100)
        op_rwg1 = AtomicOp(op_name="pulse", channel=ch_rwg1, duration=100)
        op_main = AtomicOp(op_name="pulse", channel=ch_main, duration=100)

        # 并行组合 (不同板卡，应该成功)
        parallel_01 = TensorOp(op_rwg0.result, op_rwg1.result)
        parallel_all = TensorOp(parallel_01.result, op_main.result)

        # 验证包含所有3个通道
        channels = parallel_all.result.type.get_channels()
        assert len(channels) == 3
        assert ch_rwg0 in channels
        assert ch_rwg1 in channels
        assert ch_main in channels

        print(f"\n✓ Multi-board parallel operations:")
        for ch in channels:
            print(f"  {ch.get_global_id()}")

    def test_same_board_multi_channel_parallel(self):
        """Test parallel operations on multiple channels of same board."""
        # 同一RWG板的4个TTL通道
        channels = [
            ChannelType("rwg", 0, i, "ttl")
            for i in range(4)
        ]

        # 创建并行操作
        ops = [
            AtomicOp(op_name=f"pulse_{i}", channel=ch, duration=100)
            for i, ch in enumerate(channels)
        ]

        # 逐步并行组合
        current = ops[0]
        for op in ops[1:]:
            current = TensorOp(current.result, op.result)

        # 验证包含所有4个通道
        result_channels = current.result.type.get_channels()
        assert len(result_channels) == 4

        print(f"\n✓ Same board, multiple channels:")
        for ch in result_channels:
            print(f"  {ch.get_global_id()}")

    def test_channel_accessor_methods(self):
        """Test all accessor methods return correct values."""
        ch = ChannelType("rwg", 2, 5, "ttl")

        # 测试所有访问器
        assert ch.get_board_type() == "rwg"
        assert ch.get_board_id() == 2
        assert ch.get_local_id() == 5
        assert ch.get_channel_type() == "ttl"
        assert ch.get_global_id() == "RWG_2_TTL_5"

        print(f"\n✓ Channel accessor methods work correctly:")
        print(f"  board_type:   {ch.get_board_type()}")
        print(f"  board_id:     {ch.get_board_id()}")
        print(f"  local_id:     {ch.get_local_id()}")
        print(f"  channel_type: {ch.get_channel_type()}")
        print(f"  global_id:    {ch.get_global_id()}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
