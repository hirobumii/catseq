"""测试 flatten_by_board 按板卡展平功能

验证 Morphism Arena DFS 遍历 → per-board, per-channel timeline 展平。
"""

import sys
sys.path.insert(0, "/home/tosaka/catseq")

from catseq.v2.context import (
    get_context,
    reset_context,
    flatten_by_board,
    BoardTimeline,
    ChannelTimeline,
    TimelineEvent,
)


def make_channel_id(board_id: int, local_id: int) -> int:
    """构造 channel_id: 高 16 位 board_id, 低 16 位 local_id"""
    return (board_id << 16) | local_id


# =============================================================================
# 基础测试
# =============================================================================

def test_single_atomic():
    """单个原子节点展平"""
    reset_context()
    ctx = get_context()
    ch = make_channel_id(0, 0)
    nid = ctx.atomic_id(ch, 100, 0x0100, b"\x01")

    boards = flatten_by_board(nid)
    assert len(boards) == 1

    board_id, total_dur, channels = boards[0]
    assert board_id == 0
    assert total_dur == 100
    assert len(channels) == 1

    ch_id, ch_dur, events = channels[0]
    assert ch_id == ch
    assert ch_dur == 100
    assert len(events) == 1

    time, dur, opcode, payload = events[0]
    assert time == 0
    assert dur == 100
    assert opcode == 0x0100
    assert payload == b"\x01"


def test_sequential_same_channel():
    """同通道串行组合"""
    reset_context()
    ctx = get_context()
    ch = make_channel_id(0, 0)
    a = ctx.atomic_id(ch, 100, 0x01, b"A")
    b = ctx.atomic_id(ch, 200, 0x02, b"B")
    seq = ctx.compose(a, b)

    boards = flatten_by_board(seq)
    assert len(boards) == 1

    _, total_dur, channels = boards[0]
    assert total_dur == 300
    assert len(channels) == 1

    _, ch_dur, events = channels[0]
    assert ch_dur == 300
    assert len(events) == 2
    assert events[0] == (0, 100, 0x01, b"A")
    assert events[1] == (100, 200, 0x02, b"B")


def test_parallel_same_board():
    """同板卡不同通道并行"""
    reset_context()
    ctx = get_context()
    ch0 = make_channel_id(1, 0)
    ch1 = make_channel_id(1, 1)
    a = ctx.atomic_id(ch0, 100, 0x01, b"A")
    b = ctx.atomic_id(ch1, 200, 0x02, b"B")
    par = ctx.parallel_compose(a, b)

    boards = flatten_by_board(par)
    assert len(boards) == 1

    board_id, total_dur, channels = boards[0]
    assert board_id == 1
    assert total_dur == 200  # max(100, 200)
    assert len(channels) == 2

    # 通道按 channel_id 排序
    ch0_id, ch0_dur, ch0_events = channels[0]
    ch1_id, ch1_dur, ch1_events = channels[1]
    assert ch0_id == ch0
    assert ch1_id == ch1
    # channel duration >= root_duration (padded to morphism span)
    assert ch0_dur == 200  # max(100, root_duration=200)
    assert ch1_dur == 200


def test_two_boards():
    """两个板卡并行"""
    reset_context()
    ctx = get_context()
    ch_a = make_channel_id(0, 0)
    ch_b = make_channel_id(1, 0)
    a = ctx.atomic_id(ch_a, 100, 0x01, b"A")
    b = ctx.atomic_id(ch_b, 200, 0x02, b"B")
    par = ctx.parallel_compose(a, b)

    boards = flatten_by_board(par)
    assert len(boards) == 2

    # 按 board_id 排序
    boards.sort(key=lambda x: x[0])

    b0_id, b0_dur, b0_chs = boards[0]
    b1_id, b1_dur, b1_chs = boards[1]
    assert b0_id == 0
    assert b1_id == 1
    # Both boards padded to root_duration = max(100, 200) = 200
    assert b0_dur == 200
    assert b1_dur == 200


# =============================================================================
# 复合结构测试
# =============================================================================

def test_sequential_then_parallel():
    """(A >> B) | C — 串行后并行"""
    reset_context()
    ctx = get_context()
    ch0 = make_channel_id(0, 0)
    ch1 = make_channel_id(0, 1)

    a = ctx.atomic_id(ch0, 100, 0x01, b"A")
    b = ctx.atomic_id(ch0, 150, 0x02, b"B")
    seq = ctx.compose(a, b)  # ch0: 250 total
    c = ctx.atomic_id(ch1, 200, 0x03, b"C")
    par = ctx.parallel_compose(seq, c)

    boards = flatten_by_board(par)
    assert len(boards) == 1

    _, total_dur, channels = boards[0]
    assert total_dur == 250  # max(250, 200)
    assert len(channels) == 2

    # ch0 has 2 events
    _, _, ch0_events = channels[0]
    assert len(ch0_events) == 2
    assert ch0_events[0] == (0, 100, 0x01, b"A")
    assert ch0_events[1] == (100, 150, 0x02, b"B")

    # ch1 has 1 event
    _, _, ch1_events = channels[1]
    assert len(ch1_events) == 1
    assert ch1_events[0] == (0, 200, 0x03, b"C")


def test_parallel_then_sequential():
    """(A | B) >> (C | D) — 并行后串行"""
    reset_context()
    ctx = get_context()
    ch0 = make_channel_id(0, 0)
    ch1 = make_channel_id(0, 1)

    a = ctx.atomic_id(ch0, 100, 0x01, b"A")
    b = ctx.atomic_id(ch1, 100, 0x02, b"B")
    par1 = ctx.parallel_compose(a, b)

    c = ctx.atomic_id(ch0, 200, 0x03, b"C")
    d = ctx.atomic_id(ch1, 200, 0x04, b"D")
    par2 = ctx.parallel_compose(c, d)

    seq = ctx.compose(par1, par2)

    boards = flatten_by_board(seq)
    assert len(boards) == 1

    _, total_dur, channels = boards[0]
    assert total_dur == 300  # 100 + 200

    _, _, ch0_events = channels[0]
    assert ch0_events[0] == (0, 100, 0x01, b"A")
    assert ch0_events[1] == (100, 200, 0x03, b"C")

    _, _, ch1_events = channels[1]
    assert ch1_events[0] == (0, 100, 0x02, b"B")
    assert ch1_events[1] == (100, 200, 0x04, b"D")


# =============================================================================
# 多板卡复合测试
# =============================================================================

def test_multi_board_complex():
    """多板卡、多通道、混合串并行"""
    reset_context()
    ctx = get_context()
    ch0_0 = make_channel_id(0, 0)
    ch0_1 = make_channel_id(0, 1)
    ch1_0 = make_channel_id(1, 0)

    # Board 0: ch0 sequential, ch1 single
    a = ctx.atomic_id(ch0_0, 100, 0x01, b"A")
    b = ctx.atomic_id(ch0_0, 150, 0x02, b"B")
    seq = ctx.compose(a, b)  # ch0_0: 250

    c = ctx.atomic_id(ch0_1, 200, 0x03, b"C")  # ch0_1: 200

    # Board 1: single
    d = ctx.atomic_id(ch1_0, 300, 0x04, b"D")  # ch1_0: 300

    par_board0 = ctx.parallel_compose(seq, c)
    par_all = ctx.parallel_compose(par_board0, d)

    boards = flatten_by_board(par_all)
    boards.sort(key=lambda x: x[0])
    assert len(boards) == 2

    # Board 0
    b0_id, b0_dur, b0_chs = boards[0]
    assert b0_id == 0
    # root_duration = max(250, 300) = 300, all boards padded
    assert b0_dur == 300
    assert len(b0_chs) == 2

    # Board 1
    b1_id, b1_dur, b1_chs = boards[1]
    assert b1_id == 1
    assert b1_dur == 300
    assert len(b1_chs) == 1


# =============================================================================
# 边界情况
# =============================================================================

def test_zero_duration():
    """零时长原子节点"""
    reset_context()
    ctx = get_context()
    ch = make_channel_id(0, 0)
    nid = ctx.atomic_id(ch, 0, 0x01, b"")

    boards = flatten_by_board(nid)
    assert len(boards) == 1
    _, total_dur, channels = boards[0]
    assert total_dur == 0
    _, _, events = channels[0]
    assert events[0] == (0, 0, 0x01, b"")


def test_events_sorted_by_time():
    """验证事件按时间排序"""
    reset_context()
    ctx = get_context()
    ch = make_channel_id(0, 0)

    nodes = []
    for i in range(5):
        nodes.append(ctx.atomic_id(ch, 100, i, bytes([i])))
    seq = ctx.compose_sequence(nodes)

    boards = flatten_by_board(seq)
    _, _, channels = boards[0]
    _, _, events = channels[0]

    times = [e[0] for e in events]
    assert times == sorted(times)
    assert times == [0, 100, 200, 300, 400]


# =============================================================================
# context.py 包装测试
# =============================================================================

def test_flatten_uses_global_context():
    """验证 flatten_by_board 使用全局上下文"""
    reset_context()
    ctx = get_context()
    ch = make_channel_id(2, 5)
    nid = ctx.atomic_id(ch, 42, 0xFF, b"\xAB")

    # 通过 context.py 的包装函数调用
    boards = flatten_by_board(nid)
    assert len(boards) == 1
    board_id, _, channels = boards[0]
    assert board_id == 2
    ch_id, _, events = channels[0]
    assert ch_id == ch
    assert events[0][2] == 0xFF
    assert events[0][3] == b"\xAB"


if __name__ == "__main__":
    tests = [
        test_single_atomic,
        test_sequential_same_channel,
        test_parallel_same_board,
        test_two_boards,
        test_sequential_then_parallel,
        test_parallel_then_sequential,
        test_multi_board_complex,
        test_zero_duration,
        test_events_sorted_by_time,
        test_flatten_uses_global_context,
    ]
    print("运行 flatten_by_board 测试...")
    for t in tests:
        t()
        print(f"✓ {t.__name__}")
    print(f"\n所有 {len(tests)} 个测试通过!")
