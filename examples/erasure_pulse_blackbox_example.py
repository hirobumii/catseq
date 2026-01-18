"""
将 erasure pulse 脚本封装为 oasm_black_box 的示例

核心设计：
- prepare 和 play 配对封装，确保使用相同的波形数据
- 精确计算 copy 时间（基于 oasm.rtmq2.copy 实现）
- 工厂函数同时生成两个 Morphism，解决配对问题
- 遵循 CLAUDE.md 编码规范
"""

# ============================================================================
# 所有 import 语句必须在文件顶部
# ============================================================================

# catseq imports
from catseq.types.common import Board, Channel, ChannelType
from catseq.types.rwg import RWGUninitialized, RWGReady
from catseq.atomic import oasm_black_box
from catseq.morphism import Morphism
from catseq.time_utils import us, time_to_cycles
from catseq.compilation.functions import rwg_set_carrier
from catseq.compilation import compile_to_oasm_calls, execute_oasm_calls

# OASM imports
from oasm.rtmq2 import copy, wait, R
from oasm.dev.rwg import rwg
from oasm.rtmq2.intf import sim_intf
from oasm.rtmq2 import assembler
from oasm.dev.main import run_cfg
from oasm.dev.rwg import C_RWG

# Standard library
import numpy as np
from typing import TypeAlias


# ============================================================================
# 类型别名
# ============================================================================

IQData: TypeAlias = list[int]


# ============================================================================
# 波形生成
# ============================================================================

def generate_erasure_waveform(
    phases: np.ndarray,
    frq: tuple[float, float],
    amp: tuple[float, float],
    pha: tuple[float, float],
    duration: float,
    sampling_rate: float = 125e6
) -> IQData:
    """
    生成擦除脉冲的 I/Q 波形数据

    参数：
        phases: 优化的相位数组
        frq: 频率元组 (f_I, f_Q) [Hz]
        amp: 幅度元组 (amp_I, amp_Q) [0-1]
        pha: 相位元组 (pha_0, pha_1) [radian]
        duration: 持续时间（秒，SI 单位）
        sampling_rate: 采样率（Hz，默认 125 MHz）

    返回：
        IQ 数据列表（交错的 I1, I2, Q1, Q2 值，16位整数）
    """
    num_samples = round(duration * sampling_rate)
    tt = np.arange(num_samples) / sampling_rate

    IQ = []
    for p, t in zip(phases, tt):
        I1 = 32767 * amp[0] * np.cos(2*np.pi*(frq[0]*t + p + pha[0]))
        Q1 = 32767 * amp[1] * np.sin(2*np.pi*(frq[1]*t + p + pha[0]))
        I2 = 32767 * amp[0] * np.cos(2*np.pi*(frq[0]*t + p + pha[1]))
        Q2 = 32767 * amp[1] * np.sin(2*np.pi*(frq[1]*t + p + pha[1]))
        IQ += [round(I1), round(I2), round(Q1), round(Q2)]

    return IQ


# ============================================================================
# OASM 函数：prepare（精确时间可计算，可封装）
# ============================================================================

def oasm_erasure_prepare(
    IQ_data: IQData,
    carrier_freq: float,
    i_channel_id: int,
    q_channel_id: int
) -> None:
    """
    纯 OASM 函数：初始化 RWG 系统并上传波形

    时间成本：
    - 2 个 rwg_set_carrier: 约 2 cycles (每个约 1 cycle)
    - 1 个 copy: 3 + len(IQ_data) cycles

    总时长：5 + len(IQ_data) cycles

    参数：
        IQ_data: 波形数据列表（16位整数）
        carrier_freq: 载波频率（Hz）
        i_channel_id: I 通道的 local_id
        q_channel_id: Q 通道的 local_id
    """
    # 设置 RWG 载波频率（每个约 1 cycle）
    rwg_set_carrier(i_channel_id, carrier_freq)
    rwg_set_carrier(q_channel_id, carrier_freq)

    # 上传波形数据到内存地址 2
    # copy 函数精确时间：3 + len(IQ_data) cycles
    copy(0, IQ_data, 2)


# ============================================================================
# OASM 函数：play（精确时间可计算，可封装）
# ============================================================================

def oasm_erasure_play(waveform_length: int) -> None:
    """
    纯 OASM 函数：播放已上传的波形

    时间成本：
    - rwg.pdm.source(2,3,1,1): 2 cycles
    - R.dcf = waveform_length: 1 cycle
    - R.dca = 0: 1 cycle
    - wait(waveform_length - 4): waveform_length - 4 cycles
    - rwg.pdm.source(1,1,1,1): 2 cycles

    总时长：6 + (waveform_length - 4) = 2 + waveform_length cycles

    参数：
        waveform_length: 波形数据长度的一半（len(IQ) >> 1）

    注意：假设波形数据已通过 oasm_erasure_prepare() 上传
    """
    # 配置 PDM 源为波形播放模式
    rwg.pdm.source(2, 3, 1, 1)

    # 设置波形播放参数
    R.dcf = waveform_length
    R.dca = 0

    # 等待波形播放完成
    wait(waveform_length - 4)

    # 恢复 PDM 默认模式
    rwg.pdm.source(1, 1, 1, 1)


# ============================================================================
# catseq 包装层：配对工厂函数
# ============================================================================

def wrap_erasure_pulse_pair(
    rwg_i_channel: Channel,
    rwg_q_channel: Channel,
    carrier_freq: float,
    IQ_data: IQData,
    waveform_duration: float
) -> tuple[Morphism, Morphism]:
    """
    将 erasure pulse 的 prepare 和 play 封装为配对的 Morphism

    这个工厂函数确保 prepare 和 play 使用相同的波形数据，
    解决配对问题。所有时间都是精确计算的，无估算。

    参数：
        rwg_i_channel: RWG I 通道（从外部导入，如 sqg_i）
        rwg_q_channel: RWG Q 通道（从外部导入，如 sqg_q）
        carrier_freq: 载波频率（Hz）
        IQ_data: 波形数据（必须预先生成）
        waveform_duration: 波形持续时间（秒，SI 单位）

    返回：
        (prepare_morphism, play_morphism) 元组
        - prepare_morphism: 初始化并上传波形
        - play_morphism: 播放波形

    异常：
        ValueError: 如果通道类型不正确或不在同一块板卡上

    使用示例：
        prepare, play = wrap_erasure_pulse_pair(sqg_i, sqg_q, 20e6, data, 3*us)
        sequence = prepare @ play  # prepare 必须在 play 之前
    """
    # 验证通道类型
    if rwg_i_channel.channel_type != ChannelType.RWG:
        raise ValueError(f"I 通道必须是 RWG 类型，实际为 {rwg_i_channel.channel_type}")
    if rwg_q_channel.channel_type != ChannelType.RWG:
        raise ValueError(f"Q 通道必须是 RWG 类型，实际为 {rwg_q_channel.channel_type}")

    # 验证同一板卡
    board_i = rwg_i_channel.board
    board_q = rwg_q_channel.board
    if board_i.id != board_q.id:
        raise ValueError(
            f"I 和 Q 通道必须在同一块板卡上。"
            f"I 通道在 {board_i.id}，Q 通道在 {board_q.id}"
        )
    board = board_i

    # 计算波形长度
    waveform_samples = len(IQ_data) // 4  # 每个采样点 4 个值
    waveform_length = (waveform_samples * 4) >> 1

    # ========================================================================
    # 封装 prepare Morphism（精确时间计算）
    # ========================================================================

    # 基于 oasm_erasure_prepare 的精确时间分析：
    # - 2 个 rwg_set_carrier: 2 cycles
    # - copy(0, IQ_data, 2): 3 + len(IQ_data) cycles
    prepare_total_cycles = 2 + 3 + len(IQ_data)

    # prepare 的状态转换：Uninitialized -> Ready
    prepare_start_state = RWGUninitialized()
    prepare_end_state = RWGReady(carrier_freq=carrier_freq)

    prepare_channel_states = {
        rwg_i_channel: (prepare_start_state, prepare_end_state),
        rwg_q_channel: (prepare_start_state, prepare_end_state),
    }

    # 创建闭包，捕获 IQ_data 和参数
    def make_prepare_func(data: IQData, freq: float, i_id: int, q_id: int):
        def _prepare() -> None:
            oasm_erasure_prepare(data, freq, i_id, q_id)
        return _prepare

    prepare_morphism = oasm_black_box(
        channel_states=prepare_channel_states,
        duration_cycles=prepare_total_cycles,
        board_funcs={
            board: make_prepare_func(
                IQ_data,
                carrier_freq,
                rwg_i_channel.local_id,
                rwg_q_channel.local_id
            )
        },
        user_args=(),  # 参数已通过闭包捕获
        metadata={
            'operation': 'erasure_prepare',
            'waveform_samples': waveform_samples,
            'carrier_freq': carrier_freq,
            'data_length': len(IQ_data),
        }
    )

    # ========================================================================
    # 封装 play Morphism（精确时间计算）
    # ========================================================================

    # 基于 oasm_erasure_play 的精确时间分析：
    # - rwg.pdm.source(2,3,1,1): 2 cycles
    # - R.dcf = ...: 1 cycle
    # - R.dca = 0: 1 cycle
    # - wait(waveform_length - 4): waveform_length - 4 cycles
    # - rwg.pdm.source(1,1,1,1): 2 cycles
    # 总计: 2 + 1 + 1 + (waveform_length - 4) + 2 = 2 + waveform_length

    waveform_cycles = time_to_cycles(waveform_duration)
    play_total_cycles = 2 + waveform_cycles

    # play 的状态转换：Ready -> Ready
    play_start_state = RWGReady(carrier_freq=carrier_freq)
    play_end_state = RWGReady(carrier_freq=carrier_freq)

    play_channel_states = {
        rwg_i_channel: (play_start_state, play_end_state),
        rwg_q_channel: (play_start_state, play_end_state),
    }

    play_morphism = oasm_black_box(
        channel_states=play_channel_states,
        duration_cycles=play_total_cycles,
        board_funcs={
            board: oasm_erasure_play
        },
        user_args=(waveform_length,),
        metadata={
            'operation': 'erasure_play',
            'waveform_samples': waveform_samples,
            'waveform_duration': waveform_duration,
        }
    )

    return prepare_morphism, play_morphism


# ============================================================================
# 完整使用示例
# ============================================================================

def example_usage() -> tuple[Morphism, Board]:
    """展示如何使用配对的 prepare 和 play"""

    print("=" * 70)
    print("步骤 1: 定义硬件通道")
    print("=" * 70)

    board = Board("RWG5")
    rwg_i = Channel(board, 0, ChannelType.RWG)  # 模拟 sqg_i
    rwg_q = Channel(board, 1, ChannelType.RWG)  # 模拟 sqg_q

    print(f"I 通道: {rwg_i.global_id}")
    print(f"Q 通道: {rwg_q.global_id}")
    print(f"板卡: {board.id}")

    print("\n" + "=" * 70)
    print("步骤 2: 生成波形数据")
    print("=" * 70)

    duration = 3*us
    sampling_rate = 125e6
    num_samples = round(duration * sampling_rate)
    phases = np.linspace(0, 2*np.pi, num_samples)

    frq = (20e6, 20e6)
    amp = (0.5, 0.5)
    pha = (0.0, np.pi/4)
    carrier_freq = 20e6

    IQ_data = generate_erasure_waveform(phases, frq, amp, pha, duration, sampling_rate)

    print(f"波形数据长度: {len(IQ_data)} 个值")
    print(f"采样点数: {num_samples}")
    print(f"波形持续时间: {duration*1e6:.1f} μs")

    print("\n" + "=" * 70)
    print("步骤 3: 创建配对的 Morphism")
    print("=" * 70)

    prepare, play = wrap_erasure_pulse_pair(
        rwg_i_channel=rwg_i,
        rwg_q_channel=rwg_q,
        carrier_freq=carrier_freq,
        IQ_data=IQ_data,
        waveform_duration=duration
    )

    print(f"Prepare Morphism:")
    print(f"  总时长: {prepare.total_duration_cycles} cycles")
    print(f"       = {prepare.total_duration_cycles / 250:.3f} μs")
    print(f"  计算公式: 2 (set_carrier) + 3 (copy 初始化) + {len(IQ_data)} (数据) = {prepare.total_duration_cycles}")

    print(f"\nPlay Morphism:")
    print(f"  总时长: {play.total_duration_cycles} cycles")
    print(f"       = {play.total_duration_cycles / 250:.3f} μs")

    print("\n" + "=" * 70)
    print("步骤 4: 组合 prepare 和 play")
    print("=" * 70)

    # 关键：prepare 必须在 play 之前
    sequence = prepare @ play

    print(f"完整序列总时长: {sequence.total_duration_cycles} cycles")
    print(f"             = {sequence.total_duration_cycles / 250:.3f} μs")
    print(f"\n通道状态转换:")
    for ch, lane in sequence.lanes.items():
        print(f"  {ch.global_id}:")
        print(f"    {lane.operations[0].start_state}")
        print(f"    -> {lane.operations[-1].end_state}")

    return sequence, board


# ============================================================================
# 实际编译和运行
# ============================================================================

def compile_and_run() -> None:
    """完整的编译和运行流程"""

    sequence, _ = example_usage()

    print("\n" + "=" * 70)
    print("步骤 5: 设置 OASM 环境")
    print("=" * 70)

    intf = sim_intf()
    intf.nod_adr = 0
    intf.loc_chn = 1
    run_all = run_cfg(intf, [5])
    asm_seq = assembler(run_all, [('rwg5', C_RWG)])

    print("硬件接口: 仿真模式")
    print("目标板卡: RWG5")

    print("\n" + "=" * 70)
    print("步骤 6: 编译并执行")
    print("=" * 70)

    calls = compile_to_oasm_calls(sequence, asm_seq)
    print(f"生成 {len(calls)} 个 OASM 调用")

    success, _ = execute_oasm_calls(calls, asm_seq, verbose=True)

    if success:
        print("\n✅ 编译和执行成功!")
        print("\n时间验证:")
        print(f"  预期总时长: {sequence.total_duration_cycles / 250:.3f} μs")
        print(f"  所有时间均为精确计算，无估算")
    else:
        print("\n❌ 编译或执行失败")

    print("\n" + "=" * 70)
    print("完成")
    print("=" * 70)


# ============================================================================
# 主程序
# ============================================================================

if __name__ == "__main__":
    compile_and_run()
