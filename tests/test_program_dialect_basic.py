"""
Basic tests for catseq.program dialect

演示 xDSL IR 的构建和遍历
"""

import pytest
from xdsl.context import Context
from xdsl.dialects.builtin import ModuleOp, IntegerAttr, IntegerType, StringAttr
from xdsl.ir import Block, Region
from xdsl.builder import Builder

from catseq.dialects.program_dialect import (
    ProgramDialect,
    ExecuteOp,
    SequenceOp,
    ForOp,
    IfOp,
    CompareOp,
    LogicalAndOp,
    MorphismRefType,
    ConditionType,
)
from catseq.dialects.program_utils import (
    walk_iterative,
    count_operations,
    max_nesting_depth,
)


@pytest.fixture
def ctx():
    """创建带 program dialect 的 Context"""
    context = Context()
    context.load_dialect(ProgramDialect)
    return context


def test_execute_op_basic(ctx):
    """测试基本的 ExecuteOp 创建"""
    # 创建 MorphismRefType（直接使用整数）
    morphism_ref = MorphismRefType.from_int(42)

    # 创建 ExecuteOp
    execute_op = ExecuteOp.build(attributes={"morphism_ref": morphism_ref})

    # 验证
    assert execute_op.morphism_ref.morphism_id.value.data == 42

    # 验证通过
    execute_op.verify()


def test_sequence_op_basic(ctx):
    """测试 SequenceOp 创建和遍历"""
    # 创建三个 ExecuteOp
    ref1 = MorphismRefType.from_int(1)
    ref2 = MorphismRefType.from_int(2)
    ref3 = MorphismRefType.from_int(3)

    exec1 = ExecuteOp.build(attributes={"morphism_ref": ref1})
    exec2 = ExecuteOp.build(attributes={"morphism_ref": ref2})
    exec3 = ExecuteOp.build(attributes={"morphism_ref": ref3})

    # 创建 SequenceOp
    seq_block = Block([exec1, exec2, exec3])
    seq_region = Region([seq_block])
    seq_op = SequenceOp.build(regions=[seq_region])

    # 验证
    seq_op.verify()

    # 遍历 body 中的操作
    ops = list(seq_op.body.blocks[0].ops)
    assert len(ops) == 3
    assert all(isinstance(op, ExecuteOp) for op in ops)

    # 检查 morphism_id
    morphism_ids = [op.morphism_ref.morphism_id.value.data for op in ops]
    assert morphism_ids == [1, 2, 3]


def test_for_op_basic(ctx):
    """测试 ForOp 创建"""
    # 循环体
    ref = MorphismRefType.from_int(42)
    exec_op = ExecuteOp.build(attributes={"morphism_ref": ref})

    loop_block = Block([exec_op])
    loop_region = Region([loop_block])

    # 创建 ForOp（循环 100 次）
    count_attr = IntegerAttr(100, IntegerType(64))
    for_op = ForOp.build(
        attributes={"count": count_attr},
        regions=[loop_region]
    )

    # 验证
    for_op.verify()
    assert for_op.count.value.data == 100

    # 访问 body
    body_ops = list(for_op.body.blocks[0].ops)
    assert len(body_ops) == 1
    assert isinstance(body_ops[0], ExecuteOp)


def test_nested_loops(ctx):
    """测试嵌套循环"""
    # 最内层：ExecuteOp
    ref = MorphismRefType.from_int(1)
    exec_op = ExecuteOp.build(attributes={"morphism_ref": ref})

    # 内层循环：for 10 times
    inner_block = Block([exec_op])
    inner_region = Region([inner_block])
    inner_for = ForOp.build(
        attributes={"count": IntegerAttr(10, IntegerType(64))},
        regions=[inner_region]
    )

    # 外层循环：for 5 times
    outer_block = Block([inner_for])
    outer_region = Region([outer_block])
    outer_for = ForOp.build(
        attributes={"count": IntegerAttr(5, IntegerType(64))},
        regions=[outer_region]
    )

    # 验证
    outer_for.verify()

    # 检查嵌套结构
    assert outer_for.count.value.data == 5

    inner_ops = list(outer_for.body.blocks[0].ops)
    assert len(inner_ops) == 1
    assert isinstance(inner_ops[0], ForOp)
    assert inner_ops[0].count.value.data == 10


def test_walk_traversal(ctx):
    """测试 walk() 遍历（避免栈溢出的关键）"""
    # 构建复杂的嵌套结构
    # for 3 times {
    #     sequence {
    #         execute <1>
    #         for 2 times {
    #             execute <2>
    #         }
    #         execute <3>
    #     }
    # }

    # 构建内层 for
    exec2 = ExecuteOp.build(
        attributes={"morphism_ref": MorphismRefType.from_int(2)}
    )
    inner_for = ForOp.build(
        attributes={"count": IntegerAttr(2, IntegerType(64))},
        regions=[Region([Block([exec2])])]
    )

    # 构建 sequence
    exec1 = ExecuteOp.build(
        attributes={"morphism_ref": MorphismRefType.from_int(1)}
    )
    exec3 = ExecuteOp.build(
        attributes={"morphism_ref": MorphismRefType.from_int(3)}
    )
    seq = SequenceOp.build(
        regions=[Region([Block([exec1, inner_for, exec3])])]
    )

    # 构建外层 for
    outer_for = ForOp.build(
        attributes={"count": IntegerAttr(3, IntegerType(64))},
        regions=[Region([Block([seq])])]
    )

    # 使用非递归遍历（不会栈溢出）
    all_ops = list(walk_iterative(outer_for))

    # 统计操作类型
    for_count = sum(1 for op in all_ops if isinstance(op, ForOp))
    seq_count = sum(1 for op in all_ops if isinstance(op, SequenceOp))
    exec_count = sum(1 for op in all_ops if isinstance(op, ExecuteOp))

    assert for_count == 2  # 外层 + 内层
    assert seq_count == 1
    assert exec_count == 3  # exec1, exec2, exec3

    print(f"✅ 遍历了 {len(all_ops)} 个操作（无栈溢出）")


def test_deep_nesting_no_stackoverflow(ctx):
    """测试深层嵌套不会栈溢出（关键测试）"""
    # 构建 100 层嵌套的循环
    depth = 10000

    # 最内层
    exec_op = ExecuteOp.build(
        attributes={"morphism_ref": MorphismRefType.from_int(1)}
    )

    current_op = exec_op
    for i in range(depth):
        # 包装在 ForOp 中
        loop_block = Block([current_op])
        loop_region = Region([loop_block])
        current_op = ForOp.build(
            attributes={"count": IntegerAttr(2, IntegerType(64))},
            regions=[loop_region]
        )

    # 遍历（使用非递归迭代器，不会栈溢出）
    try:
        all_ops = list(walk_iterative(current_op))
        print(f"✅ 成功遍历 {depth} 层嵌套，共 {len(all_ops)} 个操作")

        # 应该有 depth 个 ForOp + 1 个 ExecuteOp
        assert len(all_ops) == depth + 1
    except RecursionError:
        pytest.fail(f"❌ 栈溢出！深度 {depth} 层")


def test_condition_ops(ctx):
    """测试条件操作"""
    # 创建比较操作：adc_value > 500
    compare_op = CompareOp.build(
        attributes={
            "var_ref": StringAttr("adc_value"),
            "comparator": StringAttr(">"),
            "value": IntegerAttr(500, IntegerType(32))
        },
        result_types=[ConditionType()]
    )

    # 验证
    compare_op.verify()
    assert compare_op.var_ref.data == "adc_value"
    assert compare_op.comparator.data == ">"
    assert compare_op.value.value.data == 500


def test_logical_and(ctx):
    """测试逻辑与操作"""
    # 创建两个条件
    cond1 = CompareOp.build(
        attributes={
            "var_ref": StringAttr("x"),
            "comparator": StringAttr(">"),
            "value": IntegerAttr(100, IntegerType(32))
        },
        result_types=[ConditionType()]
    )

    cond2 = CompareOp.build(
        attributes={
            "var_ref": StringAttr("y"),
            "comparator": StringAttr("<"),
            "value": IntegerAttr(200, IntegerType(32))
        },
        result_types=[ConditionType()]
    )

    # 逻辑与
    and_op = LogicalAndOp.build(
        operands=[cond1.result, cond2.result],
        result_types=[ConditionType()]
    )

    # 验证
    and_op.verify()
    assert isinstance(and_op.lhs.type, ConditionType)
    assert isinstance(and_op.rhs.type, ConditionType)


def test_print_ir(ctx):
    """测试打印为 MLIR 文本格式"""
    # 构建简单程序
    exec1 = ExecuteOp.build(
        attributes={"morphism_ref": MorphismRefType.from_int(1)}
    )
    exec2 = ExecuteOp.build(
        attributes={"morphism_ref": MorphismRefType.from_int(2)}
    )

    seq = SequenceOp.build(
        regions=[Region([Block([exec1, exec2])])]
    )

    for_op = ForOp.build(
        attributes={"count": IntegerAttr(10, IntegerType(64))},
        regions=[Region([Block([seq])])]
    )

    # 创建 module
    module = ModuleOp.build(regions=[Region([Block([for_op])])])

    # 打印
    ir_text = str(module)
    print("\n" + "="*60)
    print("Generated MLIR IR:")
    print("="*60)
    print(ir_text)
    print("="*60)

    # 验证包含关键字
    assert "program.for" in ir_text
    assert "program.sequence" in ir_text
    assert "program.execute" in ir_text


if __name__ == "__main__":
    # 运行关键测试
    ctx = Context()
    ctx.load_dialect(ProgramDialect)

    print("🧪 测试 1: 深层嵌套（100 层）")
    test_deep_nesting_no_stackoverflow(ctx)

    print("\n🧪 测试 2: 复杂遍历")
    test_walk_traversal(ctx)

    print("\n🧪 测试 3: 打印 IR")
    test_print_ir(ctx)

    print("\n✅ 所有测试通过！")
