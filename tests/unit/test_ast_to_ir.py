"""
Tests for AST to xDSL IR conversion

Verifies that Program AST can be correctly converted to xDSL IR operations.
"""

import pytest
from xdsl.context import Context
from xdsl.dialects.builtin import IntegerType
from xdsl.ir import Block, Region

from catseq.ast.ast_to_ir import ASTToIRConverter, convert_ast_to_ir
from catseq.ast.program_ast import (
    MorphismStmt,
    SequenceStmt,
    ForLoopStmt,
    IfStmt,
)
from catseq.ast.variables import RuntimeVar
from catseq.ast.expressions import Condition
from catseq.dialects.program_dialect import (
    ProgramDialect,
    ExecuteOp,
    SequenceOp,
    ForOp,
    IfOp,
    CompareOp,
)
from catseq.dialects.program_utils import walk_iterative


@pytest.fixture
def ctx():
    """Create Context with program dialect"""
    context = Context()
    context.load_dialect(ProgramDialect)
    return context


@pytest.fixture
def converter():
    """Create a fresh converter for each test"""
    return ASTToIRConverter()


class DummyMorphism:
    """Dummy morphism for testing"""
    def __init__(self, name: str):
        self.name = name
    
    def __repr__(self):
        return f"Morphism({self.name})"


def test_convert_single_morphism(ctx, converter):
    """Test converting a single MorphismStmt"""
    # Create AST
    morphism = DummyMorphism("pulse1")
    ast = MorphismStmt(morphism)
    
    # Convert
    ir_op = converter.convert_node(ast)
    
    # Verify
    assert isinstance(ir_op, ExecuteOp)
    morphism_id = ir_op.morphism_ref.morphism_id.value.data
    assert converter.get_morphism(morphism_id) is morphism


def test_convert_sequence(ctx, converter):
    """Test converting a SequenceStmt"""
    # Create AST: sequence of 3 morphisms
    m1 = DummyMorphism("pulse1")
    m2 = DummyMorphism("pulse2")
    m3 = DummyMorphism("pulse3")
    
    ast = SequenceStmt((
        MorphismStmt(m1),
        MorphismStmt(m2),
        MorphismStmt(m3),
    ))
    
    # Convert
    ir_op = converter.convert_node(ast)
    
    # Verify
    assert isinstance(ir_op, SequenceOp)
    
    # Check the body contains 3 ExecuteOps
    body_ops = list(ir_op.body.blocks[0].ops)
    assert len(body_ops) == 3
    assert all(isinstance(op, ExecuteOp) for op in body_ops)
    
    # Verify morphism IDs
    morphism_ids = [op.morphism_ref.morphism_id.value.data for op in body_ops]
    retrieved = [converter.get_morphism(mid) for mid in morphism_ids]
    assert retrieved == [m1, m2, m3]


def test_convert_for_loop(ctx, converter):
    """Test converting a ForLoopStmt"""
    # Create AST: for 100 times { execute(pulse) }
    morphism = DummyMorphism("pulse")
    ast = ForLoopStmt(
        loop_var="_",
        count=100,
        body=MorphismStmt(morphism)
    )
    
    # Convert
    ir_op = converter.convert_node(ast)
    
    # Verify
    assert isinstance(ir_op, ForOp)
    assert ir_op.count.value.data == 100
    
    # Check body
    body_ops = list(ir_op.body.blocks[0].ops)
    assert len(body_ops) == 1
    assert isinstance(body_ops[0], ExecuteOp)


def test_convert_nested_loops(ctx, converter):
    """Test converting nested ForLoopStmts"""
    # Create AST: for 5 times { for 10 times { execute(pulse) } }
    morphism = DummyMorphism("pulse")
    
    inner_loop = ForLoopStmt(
        loop_var="_",
        count=10,
        body=MorphismStmt(morphism)
    )
    
    outer_loop = ForLoopStmt(
        loop_var="_",
        count=5,
        body=inner_loop
    )
    
    # Convert
    ir_op = converter.convert_node(outer_loop)
    
    # Verify
    assert isinstance(ir_op, ForOp)
    assert ir_op.count.value.data == 5
    
    # Check inner loop
    inner_ops = list(ir_op.body.blocks[0].ops)
    assert len(inner_ops) == 1
    assert isinstance(inner_ops[0], ForOp)
    assert inner_ops[0].count.value.data == 10


def test_convert_if_statement(ctx, converter):
    """Test converting an IfStmt with condition"""
    # Create AST: if (adc_value > 500) { execute(pulse_high) } else { execute(pulse_low) }
    adc_value = RuntimeVar("adc_value", 0, "int32")
    condition = Condition.from_comparison(adc_value, ">", 500)
    
    pulse_high = DummyMorphism("pulse_high")
    pulse_low = DummyMorphism("pulse_low")
    
    ast = IfStmt(
        condition=condition,
        then_branch=MorphismStmt(pulse_high),
        else_branch=MorphismStmt(pulse_low)
    )
    
    # Convert
    ir_op = converter.convert_node(ast)
    
    # Since we wrap condition ops in a sequence, the result should be a SequenceOp
    assert isinstance(ir_op, SequenceOp)
    
    # Check the sequence contains: CompareOp + IfOp
    body_ops = list(ir_op.body.blocks[0].ops)
    assert len(body_ops) == 2
    assert isinstance(body_ops[0], CompareOp)
    assert isinstance(body_ops[1], IfOp)
    
    # Verify comparison
    compare_op = body_ops[0]
    assert compare_op.var_ref.data == "adc_value"
    assert compare_op.comparator.data == ">"
    assert compare_op.value.value.data == 500
    
    # Verify if branches
    if_op = body_ops[1]
    then_ops = list(if_op.then_region.blocks[0].ops)
    else_ops = list(if_op.else_region.blocks[0].ops)
    
    assert len(then_ops) == 1
    assert isinstance(then_ops[0], ExecuteOp)
    
    assert len(else_ops) == 1
    assert isinstance(else_ops[0], ExecuteOp)


def test_convert_complex_condition(ctx, converter):
    """Test converting IfStmt with complex logical condition"""
    # Create AST: if (x > 100 && y < 200) { execute(pulse) }
    x = RuntimeVar("x", 0, "int32")
    y = RuntimeVar("y", 1, "int32")
    
    cond1 = Condition.from_comparison(x, ">", 100)
    cond2 = Condition.from_comparison(y, "<", 200)
    condition = cond1 & cond2  # Logical AND
    
    pulse = DummyMorphism("pulse")
    
    ast = IfStmt(
        condition=condition,
        then_branch=MorphismStmt(pulse),
        else_branch=None
    )
    
    # Convert
    ir_op = converter.convert_node(ast)
    
    # Should be wrapped in a sequence: [CompareOp, CompareOp, LogicalAndOp, IfOp]
    assert isinstance(ir_op, SequenceOp)
    body_ops = list(ir_op.body.blocks[0].ops)
    
    # We expect: 2 CompareOps, 1 LogicalAndOp, 1 IfOp
    assert len(body_ops) == 4
    
    # Verify the condition operations were created
    from catseq.dialects.program_dialect import LogicalAndOp
    assert isinstance(body_ops[-2], LogicalAndOp)
    assert isinstance(body_ops[-1], IfOp)


def test_convert_deep_nesting_no_stackoverflow(ctx, converter):
    """Test that conversion handles deep nesting without stack overflow"""
    # Create deeply nested AST: 1000 nested loops
    depth = 1000
    
    morphism = DummyMorphism("pulse")
    current_ast = MorphismStmt(morphism)
    
    for i in range(depth):
        current_ast = ForLoopStmt(
            loop_var="_",
            count=2,
            body=current_ast
        )
    
    # Convert (should not crash)
    ir_op = converter.convert_node(current_ast)
    
    # Verify using non-recursive walk
    all_ops = list(walk_iterative(ir_op))
    
    # Should have depth ForOps + 1 ExecuteOp
    assert len(all_ops) == depth + 1
    
    for_count = sum(1 for op in all_ops if isinstance(op, ForOp))
    exec_count = sum(1 for op in all_ops if isinstance(op, ExecuteOp))
    
    assert for_count == depth
    assert exec_count == 1


def test_convert_to_module(ctx, converter):
    """Test converting AST to complete Module"""
    # Create AST
    morphism = DummyMorphism("pulse")
    ast = SequenceStmt((
        MorphismStmt(morphism),
        ForLoopStmt(loop_var="_", count=10, body=MorphismStmt(morphism))
    ))
    
    # Convert to module
    module = converter.convert_to_module(ast)
    
    # Verify module structure
    from xdsl.dialects.builtin import ModuleOp
    assert isinstance(module, ModuleOp)
    
    # Module should contain one operation (the SequenceOp)
    module_ops = list(module.regions[0].blocks[0].ops)
    assert len(module_ops) == 1
    assert isinstance(module_ops[0], SequenceOp)


def test_convert_ast_to_ir_helper(ctx):
    """Test the helper function convert_ast_to_ir"""
    # Create simple AST
    morphism = DummyMorphism("pulse")
    ast = MorphismStmt(morphism)
    
    # Convert
    module, converter = convert_ast_to_ir(ast)
    
    # Verify
    from xdsl.dialects.builtin import ModuleOp
    assert isinstance(module, ModuleOp)
    assert isinstance(converter, ASTToIRConverter)
    
    # Verify we can retrieve the morphism
    module_ops = list(module.regions[0].blocks[0].ops)
    exec_op = module_ops[0]
    morphism_id = exec_op.morphism_ref.morphism_id.value.data
    assert converter.get_morphism(morphism_id) is morphism


def test_morphism_registry(converter):
    """Test morphism registration and retrieval"""
    m1 = DummyMorphism("pulse1")
    m2 = DummyMorphism("pulse2")
    m3 = DummyMorphism("pulse3")
    
    # Register morphisms
    id1 = converter.register_morphism(m1)
    id2 = converter.register_morphism(m2)
    id3 = converter.register_morphism(m3)
    
    # IDs should be unique and sequential
    assert id1 == 0
    assert id2 == 1
    assert id3 == 2
    
    # Retrieval should work
    assert converter.get_morphism(id1) is m1
    assert converter.get_morphism(id2) is m2
    assert converter.get_morphism(id3) is m3
    
    # Non-existent ID should raise KeyError
    with pytest.raises(KeyError):
        converter.get_morphism(999)


if __name__ == "__main__":
    # Run key tests
    from xdsl.context import Context
    
    ctx = Context()
    ctx.load_dialect(ProgramDialect)
    
    converter = ASTToIRConverter()
    
    print("🧪 测试 1: 单个 Morphism 转换")
    test_convert_single_morphism(ctx, converter)
    print("✅ 通过")
    
    print("\n🧪 测试 2: Sequence 转换")
    converter = ASTToIRConverter()
    test_convert_sequence(ctx, converter)
    print("✅ 通过")
    
    print("\n🧪 测试 3: ForLoop 转换")
    converter = ASTToIRConverter()
    test_convert_for_loop(ctx, converter)
    print("✅ 通过")
    
    print("\n🧪 测试 4: 深层嵌套（1000 层）")
    converter = ASTToIRConverter()
    test_convert_deep_nesting_no_stackoverflow(ctx, converter)
    print("✅ 通过 - 无栈溢出")
    
    print("\n🧪 测试 5: If 语句转换")
    converter = ASTToIRConverter()
    test_convert_if_statement(ctx, converter)
    print("✅ 通过")
    
    print("\n✅ 所有测试通过！AST to IR 转换正常工作！")
