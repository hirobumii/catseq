"""Integration tests with real-world examples"""

from catseq import (
    Program, execute, seq, repeat, cond, var,
    ttl_on, ttl_off, identity,
    reset_allocator,
)
from catseq.ast.program_ast import SequenceStmt, ForLoopStmt, IfStmt
from catseq.types.common import Board, Channel, ChannelType


def test_mot_experiment_with_feedback():
    """MOT 实验：基于测量反馈调整脉冲"""
    reset_allocator()

    # 定义硬件
    board = Board("RWG_0")
    ttl_mot = Channel(board, 0, ChannelType.TTL)
    ttl_probe = Channel(board, 1, ChannelType.TTL)

    # 定义操作
    mot_cooling = ttl_on(ttl_mot) @ identity(100e-6) @ ttl_off(ttl_mot)
    probe_pulse = ttl_on(ttl_probe) @ identity(10e-6) @ ttl_off(ttl_probe)

    # 测量变量
    atom_number = var("atom_number", "int32")

    # 反馈控制程序
    experiment = repeat(50,
        execute(mot_cooling)
        >> execute(probe_pulse)
        >> cond([
            (atom_number < 1000, execute(mot_cooling).replicate(2)),
        ])
    )

    # 验证程序结构
    assert isinstance(experiment.to_ast(), ForLoopStmt)
    assert experiment.to_ast().count == 50
    assert isinstance(experiment.to_ast().body, SequenceStmt)


def test_rydberg_sequence():
    """Rydberg 原子实验：多阶段脉冲序列"""
    reset_allocator()

    board = Board("RWG_0")
    ch_probe = Channel(board, 0, ChannelType.TTL)
    ch_rydberg = Channel(board, 1, ChannelType.TTL)

    # 阶段定义
    prepare = ttl_on(ch_probe) @ identity(20e-6) @ ttl_off(ch_probe)
    excite = ttl_on(ch_rydberg) @ identity(50e-6) @ ttl_off(ch_rydberg)
    measure = ttl_on(ch_probe) @ identity(10e-6) @ ttl_off(ch_probe)

    # 实验序列
    rydberg_sequence = seq(
        execute(prepare),
        execute(excite).replicate(3),
        execute(measure)
    )

    assert isinstance(rydberg_sequence.to_ast(), SequenceStmt)
    assert len(rydberg_sequence.to_ast().statements) == 3


def test_adaptive_pulse_sequence():
    """自适应脉冲序列：根据测量结果动态调整"""
    reset_allocator()

    board = Board("RWG_0")
    ch_control = Channel(board, 0, ChannelType.TTL)
    ch_measure = Channel(board, 1, ChannelType.TTL)

    # 脉冲定义
    short_pulse = ttl_on(ch_control) @ identity(10e-6) @ ttl_off(ch_control)
    medium_pulse = ttl_on(ch_control) @ identity(30e-6) @ ttl_off(ch_control)
    long_pulse = ttl_on(ch_control) @ identity(50e-6) @ ttl_off(ch_control)
    measure_pulse = ttl_on(ch_measure) @ identity(5e-6) @ ttl_off(ch_measure)

    # 测量变量
    signal_strength = var("signal_strength", "int32")

    # 自适应序列
    adaptive_sequence = repeat(20,
        execute(measure_pulse)
        >> cond([
            (signal_strength > 800, execute(long_pulse)),
            (signal_strength > 400, execute(medium_pulse)),
        ], default=execute(short_pulse))
    )

    assert isinstance(adaptive_sequence.to_ast(), ForLoopStmt)
    # 验证内部有条件分支
    body = adaptive_sequence.to_ast().body
    assert isinstance(body, SequenceStmt)


def test_quantum_gate_sequence():
    """量子门序列：模拟量子算法实验"""
    reset_allocator()

    board = Board("RWG_0")
    ch_qubit1 = Channel(board, 0, ChannelType.TTL)
    ch_qubit2 = Channel(board, 1, ChannelType.TTL)
    ch_readout = Channel(board, 2, ChannelType.TTL)

    # 门操作定义
    hadamard = ttl_on(ch_qubit1) @ identity(5e-6) @ ttl_off(ch_qubit1)
    # CNOT gate: 并行操作两个 qubit 通道
    qubit1_part = ttl_on(ch_qubit1) @ identity(10e-6) @ ttl_off(ch_qubit1)
    qubit2_part = ttl_on(ch_qubit2) @ identity(10e-6) @ ttl_off(ch_qubit2)
    cnot = qubit1_part | qubit2_part
    readout = ttl_on(ch_readout) @ identity(20e-6) @ ttl_off(ch_readout)

    # 量子电路
    bell_state_preparation = seq(
        execute(hadamard),
        execute(cnot),
        execute(readout)
    )

    assert isinstance(bell_state_preparation.to_ast(), SequenceStmt)
    assert len(bell_state_preparation.to_ast().statements) == 3


def test_error_correction_loop():
    """量子纠错循环：检测和修正错误"""
    reset_allocator()

    board = Board("RWG_0")
    ch_data = Channel(board, 0, ChannelType.TTL)
    ch_ancilla = Channel(board, 1, ChannelType.TTL)
    ch_correction = Channel(board, 2, ChannelType.TTL)

    # 操作定义
    syndrome_measure = ttl_on(ch_ancilla) @ identity(15e-6) @ ttl_off(ch_ancilla)
    correction_pulse = ttl_on(ch_correction) @ identity(10e-6) @ ttl_off(ch_correction)
    data_readout = ttl_on(ch_data) @ identity(20e-6) @ ttl_off(ch_data)

    # 纠错变量
    error_detected = var("error_detected", "bool")
    error_type = var("error_type", "int32")

    # 纠错循环
    error_correction = repeat(10,
        execute(syndrome_measure)
        >> execute(correction_pulse).when(error_detected == 1)
        >> cond([
            (error_type == 1, execute(correction_pulse).replicate(2)),
        ])
    )

    assert isinstance(error_correction.to_ast(), ForLoopStmt)
    assert error_correction.to_ast().count == 10


def test_multi_parameter_optimization():
    """多参数优化：基于多个测量值的反馈"""
    reset_allocator()

    board = Board("RWG_0")
    ch1 = Channel(board, 0, ChannelType.TTL)
    ch2 = Channel(board, 1, ChannelType.TTL)

    # 参数化脉冲
    pulse_a = ttl_on(ch1) @ identity(10e-6) @ ttl_off(ch1)
    pulse_b = ttl_on(ch2) @ identity(15e-6) @ ttl_off(ch2)
    pulse_c = ttl_on(ch1) @ identity(20e-6) @ ttl_off(ch1)

    # 多个测量变量
    param1 = var("param1", "int32")
    param2 = var("param2", "int32")
    quality = var("quality", "int32")

    # 复杂的条件逻辑
    optimization_loop = repeat(100,
        cond([
            ((param1 > 500) & (param2 > 300), execute(pulse_a)),
            ((param1 > 200) | (quality > 800), execute(pulse_b)),
        ], default=execute(pulse_c))
    )

    assert isinstance(optimization_loop.to_ast(), ForLoopStmt)


def test_hierarchical_program():
    """层次化程序：嵌套的控制结构"""
    reset_allocator()

    board = Board("RWG_0")
    ch = Channel(board, 0, ChannelType.TTL)

    # 基本脉冲
    pulse = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)

    # 测量变量
    outer_condition = var("outer_condition", "int32")
    inner_condition = var("inner_condition", "int32")

    # 层次化结构：外层循环包含条件分支，条件分支内包含内层循环
    hierarchical = repeat(5,
        cond([
            (outer_condition > 100,
                repeat(3,
                    execute(pulse).when(inner_condition > 50)
                )
            ),
        ], default=execute(pulse))
    )

    assert isinstance(hierarchical.to_ast(), ForLoopStmt)
    assert hierarchical.to_ast().count == 5


def test_parallel_channels_with_feedback():
    """并行通道反馈：多通道同时操作"""
    reset_allocator()

    board = Board("RWG_0")
    ch1 = Channel(board, 0, ChannelType.TTL)
    ch2 = Channel(board, 1, ChannelType.TTL)
    ch3 = Channel(board, 2, ChannelType.TTL)

    # 并行脉冲（使用 Morphism 的 | 操作符）
    pulse1 = ttl_on(ch1) @ identity(10e-6) @ ttl_off(ch1)
    pulse2 = ttl_on(ch2) @ identity(10e-6) @ ttl_off(ch2)
    pulse3 = ttl_on(ch3) @ identity(10e-6) @ ttl_off(ch3)

    parallel_pulse = pulse1 | pulse2 | pulse3

    # 测量变量
    channel1_result = var("channel1_result", "int32")
    channel2_result = var("channel2_result", "int32")

    # 基于多通道反馈的程序
    feedback_program = repeat(50,
        execute(parallel_pulse)
        >> cond([
            ((channel1_result > 500) & (channel2_result > 500), execute(pulse1 | pulse2)),
            (channel1_result > 500, execute(pulse1)),
            (channel2_result > 500, execute(pulse2)),
        ], default=execute(pulse3))
    )

    assert isinstance(feedback_program.to_ast(), ForLoopStmt)
