"""
完整示例：如何将纯 OASM 函数包装到 oasm_black_box

这个示例展示了从编写 OASM 函数到在 catseq 中使用的完整流程。
"""

# ============================================================================
# 导入必要的模块
# ============================================================================

from catseq.types.common import Board, Channel, ChannelType
from catseq.types.ttl import TTLState
from catseq.atomic import oasm_black_box, ttl_init, ttl_on
from catseq.morphism import Morphism, identity
from catseq.time_utils import us

from oasm.rtmq2.intf import sim_intf
from oasm.rtmq2 import assembler, disassembler, for_, end, R
from oasm.dev.main import run_cfg
from oasm.dev.rwg import C_RWG, rwg

from catseq.compilation import compile_to_oasm_calls, execute_oasm_calls


# ============================================================================
# 示例 1: 简单的 TTL 脉冲序列（无参数）
# ============================================================================

def oasm_dual_ttl_pulse():
    """
    纯 OASM 函数：生成两个通道的交错脉冲

    时序：
    - t=0: 通道 1 和 2 初始化为 OFF
    - t=10μs: 通道 1 ON
    - t=20μs: 通道 2 ON, 通道 1 OFF
    - t=30μs: 通道 2 OFF

    注意：这个函数内部没有任何 catseq 的概念，只有 OASM 代码
    """
    # 确保初始状态
    rwg.ttl.off(1)
    rwg.ttl.off(2)

    # 等待 10μs (10μs * 250 cycles/μs = 2500 cycles)
    rwg.timer(2500, wait=False)
    rwg.hold()

    # 开启通道 1
    rwg.ttl.on(1)

    # 等待 10μs
    rwg.timer(2500, wait=False)
    rwg.hold()

    # 通道切换
    rwg.ttl.off(1)
    rwg.ttl.on(2)

    # 等待 10μs
    rwg.timer(2500, wait=False)
    rwg.hold()

    # 关闭通道 2
    rwg.ttl.off(2)


def wrap_dual_ttl_pulse():
    """
    将 OASM 函数包装为 catseq Morphism

    返回：
        一个 Morphism 对象，可以与其他 Morphism 组合
    """
    # 定义硬件
    board = Board("RWG0")
    ch1 = Channel(board, 1, ChannelType.TTL)
    ch2 = Channel(board, 2, ChannelType.TTL)

    # 计算时长
    # - 2 个 ttl.off 初始化：2 cycles
    # - 1 个 ttl.on(1)：1 cycle
    # - 1 个 ttl.off(1)：1 cycle
    # - 1 个 ttl.on(2)：1 cycle
    # - 1 个 ttl.off(2)：1 cycle
    # - 3 个 timer+hold 序列：3 * 2500 = 7500 cycles
    # 总计：8 + 7500 = 7508 cycles
    duration_cycles = 7508

    # 声明通道状态（catseq 需要知道这个信息用于状态管理）
    channel_states = {
        ch1: (TTLState.OFF, TTLState.OFF),  # 开始 OFF，结束 OFF
        ch2: (TTLState.OFF, TTLState.OFF),  # 开始 OFF，结束 OFF
    }

    # 创建 black box
    return oasm_black_box(
        channel_states=channel_states,
        duration_cycles=duration_cycles,
        board_funcs={
            board: oasm_dual_ttl_pulse  # 纯 OASM 函数引用
        }
    )


# ============================================================================
# 示例 2: 带参数的 OASM 函数
# ============================================================================

def oasm_variable_pulse(pulse_duration_cycles: int, channel_id: int):
    """
    可配置的脉冲生成器

    参数：
        pulse_duration_cycles: 脉冲持续时间（时钟周期）
        channel_id: TTL 通道 ID (0-based)
    """
    # 初始化通道为 OFF
    rwg.ttl.off(channel_id)

    # 等待 5μs
    rwg.timer(1250, wait=False)
    rwg.hold()

    # 开启通道
    rwg.ttl.on(channel_id)

    # 等待指定时长
    rwg.timer(pulse_duration_cycles, wait=False)
    rwg.hold()

    # 关闭通道
    rwg.ttl.off(channel_id)


def wrap_variable_pulse(channel_id: int, pulse_duration_us: float):
    """
    包装带参数的 OASM 函数

    参数：
        channel_id: 通道 ID (1-based，与 OASM 保持一致)
        pulse_duration_us: 脉冲持续时间（微秒）

    返回：
        Morphism 对象
    """
    # 定义硬件
    board = Board("RWG0")
    channel = Channel(board, channel_id, ChannelType.TTL)

    # 转换时间单位
    pulse_cycles = int(pulse_duration_us * 250)  # μs -> cycles

    # 计算总时长
    # - 1 个 ttl.off：1 cycle
    # - 1 个 ttl.on：1 cycle
    # - 1 个 ttl.off：1 cycle
    # - 1 个 5μs timer+hold：1250 cycles
    # - 1 个可变时长 timer+hold：pulse_cycles
    total_duration = 3 + 1250 + pulse_cycles

    # 声明状态
    channel_states = {
        channel: (TTLState.OFF, TTLState.OFF)
    }

    # 创建 black box，传递参数
    return oasm_black_box(
        channel_states=channel_states,
        duration_cycles=total_duration,
        board_funcs={
            board: oasm_variable_pulse
        },
        user_args=(pulse_cycles, channel_id)  # 参数通过这里传递
    )


# ============================================================================
# 示例 3: 使用位掩码的多通道同时控制
# ============================================================================

def oasm_multi_channel_burst(mask_on: int, mask_off: int, burst_duration_cycles: int):
    """
    使用位掩码同时控制多个 TTL 通道

    参数：
        mask_on: 要开启的通道掩码（例如 0x03 = 通道 0 和 1）
        mask_off: 要关闭的通道掩码
        burst_duration_cycles: 爆发持续时间
    """
    # 初始化：关闭所有指定通道
    rwg.ttl.set(0x00)

    # 开启指定通道组
    rwg.ttl.set(mask_on)

    # 持续一段时间
    rwg.timer(burst_duration_cycles, wait=False)
    rwg.hold()

    # 关闭指定通道组
    rwg.ttl.set(mask_off)


def wrap_multi_channel_burst(channel_ids: list[int], duration_us: float):
    """
    包装多通道 burst

    参数：
        channel_ids: 要控制的通道 ID 列表（例如 [1, 2]）
        duration_us: burst 持续时间（微秒）

    返回：
        Morphism 对象
    """
    # 定义硬件
    board = Board("RWG0")

    # 创建通道对象和状态字典
    channel_states = {}
    for ch_id in channel_ids:
        channel = Channel(board, ch_id, ChannelType.TTL)
        channel_states[channel] = (TTLState.OFF, TTLState.OFF)

    # 计算掩码（假设通道 ID 对应位位置）
    # 注意：实际的位映射可能不同，需要根据硬件文档调整
    mask_on = sum(1 << (ch_id - 1) for ch_id in channel_ids)
    mask_off = 0x00

    # 转换时间
    duration_cycles = int(duration_us * 250)

    # 计算总时长
    # - 1 个 ttl.set(0x00)：1 cycle
    # - 1 个 ttl.set(mask_on)：1 cycle
    # - 1 个 timer+hold：duration_cycles
    # - 1 个 ttl.set(mask_off)：1 cycle
    total_duration = 3 + duration_cycles

    # 创建 black box
    return oasm_black_box(
        channel_states=channel_states,
        duration_cycles=total_duration,
        board_funcs={
            board: oasm_multi_channel_burst
        },
        user_args=(mask_on, mask_off, duration_cycles)
    )


# ============================================================================
# 示例 4: 复杂的循环控制（使用 OASM 循环指令）
# ============================================================================

def oasm_repeated_pulse(channel_id: int, pulse_duration: int, gap_duration: int, repeat_count: int):
    """
    生成重复脉冲序列（使用 OASM 硬件循环）

    参数：
        channel_id: TTL 通道 ID
        pulse_duration: 单次脉冲持续时间（cycles）
        gap_duration: 脉冲间隔时间（cycles）
        repeat_count: 重复次数
    """
    from oasm.rtmq2 import for_, end, R

    # 初始化
    rwg.ttl.off(channel_id)

    # 硬件循环
    for_(R[1], repeat_count)

    # 循环体：开启 -> 等待 -> 关闭 -> 等待
    rwg.ttl.on(channel_id)
    rwg.timer(pulse_duration, wait=False)
    rwg.hold()

    rwg.ttl.off(channel_id)
    rwg.timer(gap_duration, wait=False)
    rwg.hold()

    end()


def wrap_repeated_pulse(channel_id: int, pulse_us: float, gap_us: float, count: int):
    """
    包装重复脉冲

    参数：
        channel_id: 通道 ID
        pulse_us: 脉冲持续时间（微秒）
        gap_us: 间隔时间（微秒）
        count: 重复次数

    返回：
        Morphism 对象
    """
    board = Board("RWG0")
    channel = Channel(board, channel_id, ChannelType.TTL)

    # 转换时间
    pulse_cycles = int(pulse_us * 250)
    gap_cycles = int(gap_us * 250)

    # 计算总时长（包括硬件循环开销）
    # - 初始化：1 cycle
    # - 循环开销：15 + count * 26 (来自 repeat_morphism 的公式)
    # - 循环体：count * (2 + pulse_cycles + gap_cycles)
    loop_body_cycles = 2 + pulse_cycles + gap_cycles  # 2 个 ttl 操作
    total_duration = 1 + 15 + count * (26 + loop_body_cycles)

    channel_states = {
        channel: (TTLState.OFF, TTLState.OFF)
    }

    return oasm_black_box(
        channel_states=channel_states,
        duration_cycles=total_duration,
        board_funcs={
            board: oasm_repeated_pulse
        },
        user_args=(channel_id, pulse_cycles, gap_cycles, count),
        metadata={'loop_count': count, 'loop_type': 'custom'}
    )


# ============================================================================
# 示例 5: 与普通 Morphism 组合使用
# ============================================================================

def example_composition():
    """展示如何将 black box 与普通 Morphism 组合"""

    board = Board("RWG0")
    ch1 = Channel(board, 1, ChannelType.TTL)
    ch2 = Channel(board, 2, ChannelType.TTL)
    ch3 = Channel(board, 3, ChannelType.TTL)

    # 1. 使用普通 Morphism 初始化
    init_sequence = ttl_init(ch1) | ttl_init(ch2) | ttl_init(ch3)

    # 2. 创建 black box 操作
    custom_pulse = wrap_dual_ttl_pulse()

    # 3. 串行组合：初始化 -> black box
    sequence = init_sequence @ custom_pulse

    # 4. 在 black box 后添加普通操作
    # 注意：需要等待 black box 完成
    final_pulse = identity(30 * us) >> ttl_on(ch3, start_state=TTLState.OFF)

    # 5. 完整序列
    complete = sequence @ final_pulse

    return complete


def example_parallel_blackboxes():
    """展示如何并行使用多个 black box（不同板卡）"""

    board0 = Board("RWG0")
    board1 = Board("RWG1")

    # 为两个不同的板卡创建 black box
    bb0 = wrap_variable_pulse(channel_id=1, pulse_duration_us=20.0)

    # 为 board1 创建类似的操作
    ch1_board1 = Channel(board1, 1, ChannelType.TTL)
    bb1 = oasm_black_box(
        channel_states={
            ch1_board1: (TTLState.OFF, TTLState.OFF)
        },
        duration_cycles=5000,
        board_funcs={
            board1: oasm_variable_pulse
        },
        user_args=(3750, 1)  # 15μs pulse
    )

    # 并行执行（因为在不同板卡上）
    parallel = bb0 | bb1

    return parallel


# ============================================================================
# 示例 6: 实际编译和执行
# ============================================================================

def run_example():
    """完整的编译和执行示例"""

    print("=" * 70)
    print("示例 1: 简单 TTL 脉冲序列")
    print("=" * 70)

    # 创建 Morphism
    pulse_morphism = wrap_dual_ttl_pulse()

    # 打印信息
    print(f"\nMorphism 总时长: {pulse_morphism.total_duration_cycles} cycles")
    print(f"               = {pulse_morphism.total_duration_cycles / 250:.2f} μs")
    print(f"\n通道信息:")
    for channel, lane in pulse_morphism.lanes.items():
        print(f"  {channel.global_id}: {lane.operations[0].start_state} -> {lane.operations[-1].end_state}")

    # 设置 OASM 环境
    print("\n设置 OASM 环境...")
    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    run_all = run_cfg(intf, [0])
    assembler_seq = assembler(run_all, [('rwg0', C_RWG)])

    # 编译
    print("编译 Morphism...")
    calls = compile_to_oasm_calls(pulse_morphism, assembler_seq)

    print("执行 OASM 调用...")
    success, asm_seq = execute_oasm_calls(calls, assembler_seq, verbose=True)

    if success:
        print("\n✅ 编译和执行成功!")
    else:
        print("\n❌ 编译或执行失败")

    print("\n" + "=" * 70)
    print("示例 2: 带参数的可变脉冲")
    print("=" * 70)

    # 创建带参数的 Morphism
    var_pulse = wrap_variable_pulse(channel_id=2, pulse_duration_us=15.0)

    print(f"\nMorphism 总时长: {var_pulse.total_duration_cycles} cycles")
    print(f"               = {var_pulse.total_duration_cycles / 250:.2f} μs")

    # 重置 assembler
    assembler_seq = assembler(run_all, [('rwg0', C_RWG)])

    # 编译
    print("编译 Morphism...")
    calls = compile_to_oasm_calls(var_pulse, assembler_seq)

    print("执行 OASM 调用...")
    success, asm_seq = execute_oasm_calls(calls, assembler_seq, verbose=True)

    if success:
        print("\n✅ 编译和执行成功!")
    else:
        print("\n❌ 编译或执行失败")

    print("\n" + "=" * 70)
    print("示例 3: 与普通 Morphism 组合")
    print("=" * 70)

    # 创建组合序列
    combined = example_composition()

    print(f"\n组合后总时长: {combined.total_duration_cycles} cycles")
    print(f"             = {combined.total_duration_cycles / 250:.2f} μs")
    print("\n通道信息:")
    for channel, lane in combined.lanes.items():
        print(f"  {channel.global_id}: {len(lane.operations)} 个操作")

    # 编译
    assembler_seq = assembler(run_all, [('rwg0', C_RWG)])
    print("编译组合序列...")
    calls = compile_to_oasm_calls(combined, assembler_seq)

    print("执行 OASM 调用...")
    success, asm_seq = execute_oasm_calls(calls, assembler_seq, verbose=True)

    if success:
        print("\n✅ 编译和执行成功!")
    else:
        print("\n❌ 编译或执行失败")

    print("\n" + "=" * 70)
    print("示例完成")
    print("=" * 70)


# ============================================================================
# 主程序
# ============================================================================

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║  OASM Black Box 完整示例                                              ║
║                                                                      ║
║  这个示例展示了如何将纯 OASM 函数包装到 catseq 的 oasm_black_box   ║
║  中，以及如何与其他 Morphism 组合使用。                             ║
╚══════════════════════════════════════════════════════════════════════╝
    """)

    run_example()
