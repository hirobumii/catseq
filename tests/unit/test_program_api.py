"""Unit tests for Program API"""

import pytest
from catseq import (
    Program, execute, seq, repeat, cond, if_then_else, var,
    ttl_on, ttl_off, identity,
    reset_allocator,
)
from catseq.ast.program_ast import MorphismStmt, SequenceStmt, ForLoopStmt, IfStmt
from catseq.types.common import Board, Channel, ChannelType


@pytest.fixture(autouse=True)
def reset_var_allocator():
    """每个测试前重置变量分配器"""
    reset_allocator()


def test_execute_creates_morphism_stmt():
    """测试 execute() 创建 MorphismStmt"""
    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)
    program = execute(pulse)

    assert isinstance(program, Program)
    assert isinstance(program.to_ast(), MorphismStmt)
    assert program.to_ast().morphism is pulse


def test_sequential_composition():
    """测试 >> 操作符"""
    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse1 = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)
    pulse2 = ttl_on(ch) @ identity(20e-6) @ ttl_off(ch)

    program = execute(pulse1) >> execute(pulse2)

    assert isinstance(program.to_ast(), SequenceStmt)
    assert len(program.to_ast().statements) == 2


def test_seq_helper():
    """测试 seq() 辅助函数"""
    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)

    program = seq(
        execute(pulse),
        execute(pulse),
        execute(pulse)
    )

    assert isinstance(program.to_ast(), SequenceStmt)
    assert len(program.to_ast().statements) == 3


def test_replicate():
    """测试 replicate() 循环"""
    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)
    program = execute(pulse).replicate(100)

    assert isinstance(program.to_ast(), ForLoopStmt)
    assert program.to_ast().count == 100
    assert program.to_ast().loop_var == "_"


def test_repeat_helper():
    """测试 repeat() 辅助函数"""
    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)
    program = repeat(50, execute(pulse))

    assert isinstance(program.to_ast(), ForLoopStmt)
    assert program.to_ast().count == 50


def test_replicate_invalid_count():
    """测试 replicate() 对无效计数的验证"""
    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)

    with pytest.raises(ValueError, match="Replication count must be positive"):
        execute(pulse).replicate(0)

    with pytest.raises(ValueError, match="Replication count must be positive"):
        execute(pulse).replicate(-1)


def test_runtime_variable():
    """测试运行时变量声明"""
    adc_value = var("adc_value", "int32")

    assert adc_value.name == "adc_value"
    assert adc_value.var_type == "int32"
    assert adc_value.register_id == 0x20  # 第一个分配的寄存器


def test_runtime_variable_allocation():
    """测试多个变量的寄存器分配"""
    var1 = var("var1", "int32")
    var2 = var("var2", "int32")
    var3 = var("var3", "bool")

    assert var1.register_id == 0x20
    assert var2.register_id == 0x21
    assert var3.register_id == 0x22


def test_runtime_variable_reuse():
    """测试变量名重用返回相同寄存器"""
    var1 = var("same_var", "int32")
    var2 = var("same_var", "int32")

    assert var1.register_id == var2.register_id


def test_runtime_variable_comparison():
    """测试运行时变量比较操作"""
    adc_value = var("adc_value", "int32")

    cond_gt = adc_value > 500
    cond_lt = adc_value < 1000
    cond_eq = adc_value == 750
    cond_ne = adc_value != 0
    cond_ge = adc_value >= 500
    cond_le = adc_value <= 1000

    # 验证 Condition 对象创建成功
    from catseq.ast.expressions import Condition
    assert isinstance(cond_gt, Condition)
    assert isinstance(cond_lt, Condition)
    assert isinstance(cond_eq, Condition)
    assert isinstance(cond_ne, Condition)
    assert isinstance(cond_ge, Condition)
    assert isinstance(cond_le, Condition)


def test_if_then_else():
    """测试 if_then_else 分支"""
    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse_high = ttl_on(ch) @ identity(50e-6) @ ttl_off(ch)
    pulse_low = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)

    adc_value = var("adc_value", "int32")

    program = if_then_else(
        adc_value > 500,
        then_prog=execute(pulse_high),
        else_prog=execute(pulse_low)
    )

    assert isinstance(program.to_ast(), IfStmt)
    assert program.to_ast().then_branch is not None
    assert program.to_ast().else_branch is not None


def test_cond_single_branch():
    """测试 cond 单分支（无 default）"""
    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)
    flag = var("flag", "bool")

    program = cond([
        (flag == 1, execute(pulse)),
    ])

    assert isinstance(program.to_ast(), IfStmt)
    assert program.to_ast().else_branch is None


def test_cond_multiple_branches():
    """测试 cond 多路分支"""
    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse1 = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)
    pulse2 = ttl_on(ch) @ identity(20e-6) @ ttl_off(ch)
    pulse3 = ttl_on(ch) @ identity(30e-6) @ ttl_off(ch)

    adc_value = var("adc_value", "int32")

    program = cond([
        (adc_value > 1000, execute(pulse1)),
        (adc_value > 500,  execute(pulse2)),
    ], default=execute(pulse3))

    # cond 创建嵌套的 IfStmt
    assert isinstance(program.to_ast(), IfStmt)
    assert program.to_ast().then_branch is not None
    assert program.to_ast().else_branch is not None


def test_cond_empty_branches():
    """测试 cond 空分支列表"""
    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)

    # 无分支，有 default
    program = cond([], default=execute(pulse))
    assert isinstance(program, Program)

    # 无分支，无 default - 返回空程序
    program_empty = cond([])
    assert isinstance(program_empty, Program)
    assert isinstance(program_empty.to_ast(), SequenceStmt)
    assert len(program_empty.to_ast().statements) == 0


def test_when_condition():
    """测试 when() 条件执行"""
    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)
    flag = var("ready", "bool")

    program = execute(pulse).when(flag == 1)

    assert isinstance(program.to_ast(), IfStmt)
    assert program.to_ast().then_branch is not None
    assert program.to_ast().else_branch is None  # when 没有 else


def test_unless_condition():
    """测试 unless() 条件执行"""
    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)
    flag = var("error", "bool")

    program = execute(pulse).unless(flag == 1)

    assert isinstance(program.to_ast(), IfStmt)
    assert program.to_ast().then_branch is not None
    # unless 使用 negate，所以 condition 被否定


def test_condition_logical_operators():
    """测试条件逻辑运算符"""
    var1 = var("var1", "int32")
    var2 = var("var2", "int32")

    cond1 = var1 > 100
    cond2 = var2 < 500

    # 逻辑与
    cond_and = cond1 & cond2
    from catseq.ast.expressions import Condition
    assert isinstance(cond_and, Condition)

    # 逻辑或
    cond_or = cond1 | cond2
    assert isinstance(cond_or, Condition)

    # 逻辑非
    cond_not = cond1.negate()
    assert isinstance(cond_not, Condition)


def test_complex_program():
    """测试复杂的组合程序"""
    board = Board("test_board")
    ch1 = Channel(board, 0, ChannelType.TTL)
    ch2 = Channel(board, 1, ChannelType.TTL)

    initialize = ttl_on(ch1) @ identity(5e-6) @ ttl_off(ch1)
    measure = ttl_on(ch2) @ identity(10e-6) @ ttl_off(ch2)
    pulse_high = ttl_on(ch1) @ identity(50e-6) @ ttl_off(ch1)
    pulse_low = ttl_on(ch1) @ identity(10e-6) @ ttl_off(ch1)
    cleanup = ttl_off(ch1) @ ttl_off(ch2)

    adc_value = var("adc_value", "int32")

    experiment = (
        execute(initialize)
        >> repeat(10,
            execute(measure)
            >> cond([
                (adc_value > 500, execute(pulse_high)),
            ], default=execute(pulse_low))
        )
        >> execute(cleanup)
    )

    # 验证 AST 结构
    assert isinstance(experiment.to_ast(), SequenceStmt)
    assert len(experiment.to_ast().statements) == 3

    # 第二个语句应该是 ForLoopStmt
    assert isinstance(experiment.to_ast().statements[1], ForLoopStmt)


def test_program_string_representation():
    """测试 Program 的字符串表示"""
    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)
    program = execute(pulse)

    program_str = str(program)
    assert "Program" in program_str
    assert "Execute" in program_str


def test_nested_loops():
    """测试嵌套循环"""
    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)

    # 嵌套循环：外层 5 次，内层 10 次
    inner_loop = execute(pulse).replicate(10)
    outer_loop = inner_loop.replicate(5)

    assert isinstance(outer_loop.to_ast(), ForLoopStmt)
    assert outer_loop.to_ast().count == 5
    assert isinstance(outer_loop.to_ast().body, ForLoopStmt)
    assert outer_loop.to_ast().body.count == 10


def test_compile_time_param():
    """测试编译时参数"""
    from catseq.ast.variables import CompileTimeParam

    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)
    n = CompileTimeParam("iterations", 100)

    program = execute(pulse).replicate(n)

    assert isinstance(program.to_ast(), ForLoopStmt)
    assert program.to_ast().count is n
    assert program.to_ast().count.value == 100


def test_sequence_flattening():
    """测试序列自动扁平化"""
    board = Board("test_board")
    ch = Channel(board, 0, ChannelType.TTL)

    pulse = ttl_on(ch) @ identity(10e-6) @ ttl_off(ch)

    # 连续的 >> 操作应该自动扁平化
    program = execute(pulse) >> execute(pulse) >> execute(pulse) >> execute(pulse)

    assert isinstance(program.to_ast(), SequenceStmt)
    # 应该只有一层 SequenceStmt，包含 4 个 MorphismStmt
    assert len(program.to_ast().statements) == 4
    assert all(isinstance(stmt, MorphismStmt) for stmt in program.to_ast().statements)
