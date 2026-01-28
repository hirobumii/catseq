"""测试 ProgramArena - Program 层的 Rust 后端

验证 ProgramArena 的所有 Value 和 Node 创建、查询功能。
"""

import pytest
import catseq_rs


class TestProgramArenaBasic:
    """基础功能测试"""

    def test_create_arena(self):
        """测试创建空 Arena"""
        arena = catseq_rs.ProgramArena()
        assert arena.node_count() == 0
        assert arena.value_count() == 0
        assert arena.var_count() == 0

    def test_create_with_capacity(self):
        """测试带预分配容量创建"""
        arena = catseq_rs.ProgramArena.with_capacity(100, 200)
        assert arena.node_count() == 0
        assert arena.value_count() == 0

    def test_repr(self):
        """测试 __repr__"""
        arena = catseq_rs.ProgramArena()
        repr_str = repr(arena)
        assert "ProgramArena" in repr_str
        assert "nodes=0" in repr_str
        assert "values=0" in repr_str

    def test_clear(self):
        """测试清空 Arena"""
        arena = catseq_rs.ProgramArena()

        # 添加一些内容
        arena.variable("x", "int32")
        arena.literal(42)
        arena.identity()

        assert arena.node_count() > 0
        assert arena.value_count() > 0
        assert arena.var_count() > 0

        # 清空
        arena.clear()

        assert arena.node_count() == 0
        assert arena.value_count() == 0
        assert arena.var_count() == 0


class TestValueCreation:
    """Value 创建测试"""

    def test_literal_int(self):
        """测试创建整数字面量"""
        arena = catseq_rs.ProgramArena()

        val_id = arena.literal(42)
        assert val_id == 0
        assert arena.is_literal(val_id)
        assert not arena.is_variable(val_id)
        assert arena.get_literal_int(val_id) == 42
        assert arena.value_count() == 1

    def test_literal_negative(self):
        """测试负数字面量"""
        arena = catseq_rs.ProgramArena()

        val_id = arena.literal(-100)
        assert arena.get_literal_int(val_id) == -100

    def test_literal_large(self):
        """测试大整数字面量"""
        arena = catseq_rs.ProgramArena()

        large_val = 2**60
        val_id = arena.literal(large_val)
        assert arena.get_literal_int(val_id) == large_val

    def test_literal_float(self):
        """测试浮点数字面量"""
        arena = catseq_rs.ProgramArena()

        val_id = arena.literal_float(3.14159)
        assert val_id == 0
        assert arena.is_literal(val_id)
        result = arena.get_literal_float(val_id)
        assert result is not None
        assert abs(result - 3.14159) < 1e-10

    def test_literal_float_negative(self):
        """测试负浮点数"""
        arena = catseq_rs.ProgramArena()

        val_id = arena.literal_float(-2.718)
        result = arena.get_literal_float(val_id)
        assert result is not None
        assert abs(result - (-2.718)) < 1e-10

    def test_variable_creation(self):
        """测试创建变量"""
        arena = catseq_rs.ProgramArena()

        x_id = arena.variable("x", "int32")
        assert x_id == 0
        assert arena.is_variable(x_id)
        assert not arena.is_literal(x_id)
        assert arena.get_variable_name(x_id) == "x"
        assert arena.var_count() == 1

    def test_variable_same_name_reuse(self):
        """测试同名变量复用"""
        arena = catseq_rs.ProgramArena()

        x_id1 = arena.variable("x", "int32")
        x_id2 = arena.variable("x", "int64")  # 同名，不同类型提示

        # 应该返回相同的 ID
        assert x_id1 == x_id2
        assert arena.var_count() == 1

    def test_variable_different_names(self):
        """测试不同名变量"""
        arena = catseq_rs.ProgramArena()

        x_id = arena.variable("x", "int32")
        y_id = arena.variable("y", "float32")

        assert x_id != y_id
        assert arena.var_count() == 2
        assert arena.get_variable_name(x_id) == "x"
        assert arena.get_variable_name(y_id) == "y"

    def test_variable_type_hints(self):
        """测试各种类型提示"""
        arena = catseq_rs.ProgramArena()

        # 支持的类型提示
        type_hints = ["int32", "int64", "float32", "float64", "bool"]
        for i, hint in enumerate(type_hints):
            var_id = arena.variable(f"var_{i}", hint)
            assert arena.is_variable(var_id)

    def test_binary_expr(self):
        """测试二元表达式"""
        arena = catseq_rs.ProgramArena()

        x = arena.variable("x", "int32")
        ten = arena.literal(10)
        expr = arena.binary_expr(x, "+", ten)

        assert arena.value_count() == 3
        assert not arena.is_literal(expr)
        assert not arena.is_variable(expr)

    def test_binary_expr_operators(self):
        """测试各种二元操作符"""
        arena = catseq_rs.ProgramArena()

        a = arena.literal(10)
        b = arena.literal(3)

        operators = ["+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>"]
        for op in operators:
            expr = arena.binary_expr(a, op, b)
            assert expr is not None

    def test_unary_expr(self):
        """测试一元表达式"""
        arena = catseq_rs.ProgramArena()

        x = arena.variable("x", "int32")

        # 测试各种一元操作符
        neg = arena.unary_expr("-", x)
        not_expr = arena.unary_expr("!", x)
        bitnot = arena.unary_expr("~", x)

        assert arena.value_count() == 4  # x + 3 expressions

    def test_condition(self):
        """测试条件表达式"""
        arena = catseq_rs.ProgramArena()

        x = arena.variable("x", "int32")
        zero = arena.literal(0)
        cond = arena.condition(x, ">", zero)

        assert arena.value_count() == 3

    def test_condition_operators(self):
        """测试各种比较操作符"""
        arena = catseq_rs.ProgramArena()

        a = arena.literal(10)
        b = arena.literal(5)

        operators = ["==", "!=", "<", "<=", ">", ">="]
        for op in operators:
            cond = arena.condition(a, op, b)
            assert cond is not None

    def test_logical_expr_binary(self):
        """测试二元逻辑表达式"""
        arena = catseq_rs.ProgramArena()

        x = arena.variable("x", "bool")
        y = arena.variable("y", "bool")

        # and
        and_expr = arena.logical_expr(x, "and", y)
        assert and_expr is not None

        # or
        or_expr = arena.logical_expr(x, "or", y)
        assert or_expr is not None

    def test_logical_expr_unary(self):
        """测试一元逻辑表达式 (NOT)"""
        arena = catseq_rs.ProgramArena()

        x = arena.variable("x", "bool")

        # not (没有右操作数)
        not_expr = arena.logical_expr(x, "not")
        assert not_expr is not None


class TestNodeCreation:
    """Node 创建测试"""

    def test_identity(self):
        """测试 Identity 节点"""
        arena = catseq_rs.ProgramArena()

        node_id = arena.identity()
        assert node_id == 0
        assert arena.node_count() == 1

    def test_delay(self):
        """测试 Delay 节点"""
        arena = catseq_rs.ProgramArena()

        duration = arena.literal(1000)
        delay_id = arena.delay(duration)

        assert arena.node_count() == 1
        assert arena.value_count() == 1

    def test_delay_with_max_hint(self):
        """测试带 max_hint 的 Delay 节点"""
        arena = catseq_rs.ProgramArena()

        duration = arena.variable("t", "int32")
        delay_id = arena.delay(duration, max_hint=10000)

        assert arena.node_count() == 1

    def test_set_var(self):
        """测试 Set 节点（变量赋值）"""
        arena = catseq_rs.ProgramArena()

        x = arena.variable("x", "int32")
        val = arena.literal(42)
        set_id = arena.set_var(x, val)

        assert arena.node_count() == 1

    def test_chain(self):
        """测试 Chain 节点"""
        arena = catseq_rs.ProgramArena()

        dur1 = arena.literal(100)
        dur2 = arena.literal(200)
        delay1 = arena.delay(dur1)
        delay2 = arena.delay(dur2)
        chained = arena.chain(delay1, delay2)

        assert arena.node_count() == 3

    def test_loop(self):
        """测试 Loop 节点"""
        arena = catseq_rs.ProgramArena()

        count = arena.literal(10)
        body = arena.identity()
        loop_id = arena.loop_(count, body)

        assert arena.node_count() == 2

    def test_match(self):
        """测试 Match 节点"""
        arena = catseq_rs.ProgramArena()

        x = arena.variable("x", "int32")
        branch_a = arena.identity()
        branch_b = arena.identity()

        cases = {0: branch_a, 1: branch_b}
        match_id = arena.match_(x, cases)

        assert arena.node_count() == 3

    def test_match_with_default(self):
        """测试带 default 的 Match 节点"""
        arena = catseq_rs.ProgramArena()

        x = arena.variable("x", "int32")
        branch_a = arena.identity()
        default_branch = arena.identity()

        cases = {0: branch_a}
        match_id = arena.match_(x, cases, default=default_branch)

        assert arena.node_count() == 3

    def test_lift(self):
        """测试 Lift 节点"""
        arena = catseq_rs.ProgramArena()

        duration = arena.variable("t", "int32")
        amplitude = arena.literal_float(0.5)

        params = {"duration": duration, "amplitude": amplitude}
        lift_id = arena.lift(12345, params)

        assert arena.node_count() == 1
        assert arena.value_count() == 2

    def test_func_def(self):
        """测试 FuncDef 节点"""
        arena = catseq_rs.ProgramArena()

        # 定义函数: fn pulse(t) { delay(t) }
        param_t = arena.variable("_arg_pulse_t", "int32")
        body = arena.delay(param_t)
        func_id = arena.func_def("pulse", [param_t], body)

        assert arena.node_count() == 2  # delay + func_def

    def test_apply(self):
        """测试 Apply 节点（函数调用）"""
        arena = catseq_rs.ProgramArena()

        # 定义函数
        param_t = arena.variable("_arg_pulse_t", "int32")
        body = arena.delay(param_t)
        func_id = arena.func_def("pulse", [param_t], body)

        # 调用函数: pulse(100)
        arg = arena.literal(100)
        call_id = arena.apply(func_id, [arg])

        assert arena.node_count() == 3  # delay, func_def, apply

    def test_measure(self):
        """测试 Measure 节点"""
        arena = catseq_rs.ProgramArena()

        result_var = arena.variable("result", "int32")
        measure_id = arena.measure(result_var, source=0)

        assert arena.node_count() == 1


class TestChainSequence:
    """chain_sequence 批量组合测试"""

    def test_chain_sequence_empty(self):
        """测试空列表"""
        arena = catseq_rs.ProgramArena()
        result = arena.chain_sequence([])
        assert result is None

    def test_chain_sequence_single(self):
        """测试单元素列表"""
        arena = catseq_rs.ProgramArena()
        node = arena.identity()
        result = arena.chain_sequence([node])
        assert result == node

    def test_chain_sequence_two(self):
        """测试两个节点"""
        arena = catseq_rs.ProgramArena()

        n1 = arena.identity()
        n2 = arena.identity()
        result = arena.chain_sequence([n1, n2])

        assert result is not None
        assert arena.node_count() == 3  # 2 identity + 1 chain

    def test_chain_sequence_many(self):
        """测试多个节点（构建平衡树）"""
        arena = catseq_rs.ProgramArena()

        # 创建 10 个 identity 节点
        nodes = [arena.identity() for _ in range(10)]
        initial_count = arena.node_count()

        # Chain 组合
        result = arena.chain_sequence(nodes)
        assert result is not None

        # 应该创建了额外的 chain 节点
        assert arena.node_count() > initial_count

    def test_chain_sequence_power_of_two(self):
        """测试 2 的幂次个节点（完美平衡树）"""
        arena = catseq_rs.ProgramArena()

        nodes = [arena.identity() for _ in range(8)]
        result = arena.chain_sequence(nodes)

        assert result is not None
        # 8 个叶节点 + 7 个内部节点 = 15
        assert arena.node_count() == 15


class TestQueryMethods:
    """查询方法测试"""

    def test_is_literal_for_int(self):
        """测试 is_literal 对整数"""
        arena = catseq_rs.ProgramArena()
        val = arena.literal(42)
        assert arena.is_literal(val) is True

    def test_is_literal_for_float(self):
        """测试 is_literal 对浮点数"""
        arena = catseq_rs.ProgramArena()
        val = arena.literal_float(3.14)
        assert arena.is_literal(val) is True

    def test_is_literal_for_variable(self):
        """测试 is_literal 对变量返回 False"""
        arena = catseq_rs.ProgramArena()
        var = arena.variable("x", "int32")
        assert arena.is_literal(var) is False

    def test_is_literal_for_expr(self):
        """测试 is_literal 对表达式返回 False"""
        arena = catseq_rs.ProgramArena()
        a = arena.literal(1)
        b = arena.literal(2)
        expr = arena.binary_expr(a, "+", b)
        assert arena.is_literal(expr) is False

    def test_is_variable_for_variable(self):
        """测试 is_variable 对变量"""
        arena = catseq_rs.ProgramArena()
        var = arena.variable("x", "int32")
        assert arena.is_variable(var) is True

    def test_is_variable_for_literal(self):
        """测试 is_variable 对字面量返回 False"""
        arena = catseq_rs.ProgramArena()
        val = arena.literal(42)
        assert arena.is_variable(val) is False

    def test_get_literal_int_for_int(self):
        """测试 get_literal_int 对整数"""
        arena = catseq_rs.ProgramArena()
        val = arena.literal(42)
        assert arena.get_literal_int(val) == 42

    def test_get_literal_int_for_float(self):
        """测试 get_literal_int 对浮点数返回 None"""
        arena = catseq_rs.ProgramArena()
        val = arena.literal_float(3.14)
        assert arena.get_literal_int(val) is None

    def test_get_literal_float_for_float(self):
        """测试 get_literal_float 对浮点数"""
        arena = catseq_rs.ProgramArena()
        val = arena.literal_float(3.14)
        result = arena.get_literal_float(val)
        assert result is not None
        assert abs(result - 3.14) < 1e-10

    def test_get_literal_float_for_int(self):
        """测试 get_literal_float 对整数返回 None"""
        arena = catseq_rs.ProgramArena()
        val = arena.literal(42)
        assert arena.get_literal_float(val) is None

    def test_get_variable_name(self):
        """测试 get_variable_name"""
        arena = catseq_rs.ProgramArena()
        var = arena.variable("my_var", "int32")
        assert arena.get_variable_name(var) == "my_var"

    def test_get_variable_name_for_literal(self):
        """测试 get_variable_name 对字面量返回 None"""
        arena = catseq_rs.ProgramArena()
        val = arena.literal(42)
        assert arena.get_variable_name(val) is None

    def test_invalid_value_id(self):
        """测试无效的 ValueId"""
        arena = catseq_rs.ProgramArena()
        # 没有任何值，访问 ID 999
        assert arena.is_literal(999) is False
        assert arena.is_variable(999) is False
        assert arena.get_literal_int(999) is None
        assert arena.get_literal_float(999) is None
        assert arena.get_variable_name(999) is None


class TestComplexScenarios:
    """复杂场景测试"""

    def test_nested_expressions(self):
        """测试嵌套表达式: (x + 10) * 2"""
        arena = catseq_rs.ProgramArena()

        x = arena.variable("x", "int32")
        ten = arena.literal(10)
        two = arena.literal(2)

        add_expr = arena.binary_expr(x, "+", ten)
        mul_expr = arena.binary_expr(add_expr, "*", two)

        assert arena.value_count() == 5

    def test_complex_condition(self):
        """测试复杂条件: (x > 0) and (x < 100)"""
        arena = catseq_rs.ProgramArena()

        x = arena.variable("x", "int32")
        zero = arena.literal(0)
        hundred = arena.literal(100)

        cond1 = arena.condition(x, ">", zero)
        cond2 = arena.condition(x, "<", hundred)
        combined = arena.logical_expr(cond1, "and", cond2)

        assert arena.value_count() == 6

    def test_loop_with_counter(self):
        """测试带计数器的循环"""
        arena = catseq_rs.ProgramArena()

        # i = i + 1
        i = arena.variable("i", "int32")
        one = arena.literal(1)
        i_plus_one = arena.binary_expr(i, "+", one)
        increment = arena.set_var(i, i_plus_one)

        # loop 10 times
        count = arena.literal(10)
        loop_id = arena.loop_(count, increment)

        assert arena.node_count() == 2

    def test_conditional_branching(self):
        """测试条件分支"""
        arena = catseq_rs.ProgramArena()

        x = arena.variable("x", "int32")

        # 三个分支
        branch_0 = arena.identity()
        dur1 = arena.literal(100)
        branch_1 = arena.delay(dur1)
        dur2 = arena.literal(200)
        branch_2 = arena.delay(dur2)

        cases = {0: branch_0, 1: branch_1, 2: branch_2}
        match_id = arena.match_(x, cases)

        assert arena.node_count() == 4  # 1 identity + 2 delay + 1 match

    def test_function_with_multiple_params(self):
        """测试多参数函数"""
        arena = catseq_rs.ProgramArena()

        # fn add_delays(t1, t2) { chain(delay(t1), delay(t2)) }
        t1 = arena.variable("_arg_t1", "int32")
        t2 = arena.variable("_arg_t2", "int32")

        delay1 = arena.delay(t1)
        delay2 = arena.delay(t2)
        body = arena.chain(delay1, delay2)

        func_id = arena.func_def("add_delays", [t1, t2], body)

        # 调用: add_delays(100, 200)
        arg1 = arena.literal(100)
        arg2 = arena.literal(200)
        call_id = arena.apply(func_id, [arg1, arg2])

        assert arena.node_count() == 5  # 2 delay + 1 chain + 1 func_def + 1 apply


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
