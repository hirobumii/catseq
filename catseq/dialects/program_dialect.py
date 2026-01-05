"""
catseq.program Dialect - 控制流层 (xDSL Implementation)

这个 dialect 表示控制流结构（循环、条件分支等），是 Morphism 层之上的抽象。
"""

from xdsl.irdl import (
    irdl_attr_definition,
    irdl_op_definition,
    IRDLOperation,
    ParametrizedAttribute,
    param_def,
    attr_def,
    region_def,
    operand_def,
    result_def,
    traits_def,
)
from xdsl.ir import Attribute, Dialect
from xdsl.dialects.builtin import IntAttr, IntegerAttr, IntegerType, StringAttr
from xdsl.parser import AttrParser
from xdsl.printer import Printer
from xdsl.traits import NoTerminator


# ============================================================================
# Types
# ============================================================================

@irdl_attr_definition
class MorphismRefType(ParametrizedAttribute):
    """Morphism 引用类型（跨 dialect 引用）

    表示对一个 Morphism 对象的引用，通过唯一 ID 标识。

    语法: !program.morphism_ref<42>
    """
    name = "program.morphism_ref"

    morphism_id: IntegerAttr = param_def(IntegerAttr)

    @staticmethod
    def from_int(val: int) -> "MorphismRefType":
        """从整数创建 MorphismRefType"""
        return MorphismRefType.new([IntegerAttr.from_int_and_width(val, 64)])

    def print_parameters(self, printer: Printer) -> None:
        printer.print_string(f"<{self.morphism_id.value.data}>")

    @classmethod
    def parse_parameters(cls, parser: AttrParser) -> list[Attribute]:
        parser.parse_punctuation("<")
        morphism_id = parser.parse_integer()
        parser.parse_punctuation(">")
        return [IntegerAttr.from_int_and_width(morphism_id, 64)]


@irdl_attr_definition
class ConditionType(ParametrizedAttribute):
    """条件表达式类型

    表示一个布尔条件，可以是：
    - 比较操作（var > value）
    - 逻辑组合（cond1 && cond2）

    语法: !program.condition
    """
    name = "program.condition"

    def print_parameters(self, printer: Printer) -> None:
        pass

    @classmethod
    def parse_parameters(cls, parser: AttrParser) -> list[Attribute]:
        return []


@irdl_attr_definition
class LoopVarType(ParametrizedAttribute):
    """循环变量类型

    表示一个循环迭代变量（i = 0, 1, 2, ...）

    语法: !program.loop_var
    """
    name = "program.loop_var"

    def print_parameters(self, printer: Printer) -> None:
        pass

    @classmethod
    def parse_parameters(cls, parser: AttrParser) -> list[Attribute]:
        return []


# ============================================================================
# Operations - 控制流
# ============================================================================

@irdl_op_definition
class ExecuteOp(IRDLOperation):
    """执行单个 Morphism

    这是控制流层的叶子节点，表示执行一个物理操作序列。

    语法:
        program.execute <42>

    属性:
        morphism_ref: MorphismRefType - Morphism 的唯一 ID

    示例:
        // 执行 ID 为 42 的 Morphism
        program.execute <42>
    """
    name = "program.execute"

    morphism_ref: MorphismRefType = attr_def(MorphismRefType)

    assembly_format = "$morphism_ref attr-dict"

    def verify_(self) -> None:
        # morphism_id 必须 >= 0
        if self.morphism_ref.morphism_id.value.data < 0:
            raise ValueError(f"Invalid morphism_id: {self.morphism_ref.morphism_id.value.data}")


@irdl_op_definition
class SequenceOp(IRDLOperation):
    """顺序执行多个操作

    使用 xDSL Region 存储子操作序列，自动获得遍历能力。

    语法:
        program.sequence {
            program.execute <1>
            program.execute <2>
            program.for 10 { ... }
        }

    区域:
        body: single_block - 包含顺序执行的操作

    示例:
        program.sequence {
            program.execute <1>
            program.execute <2>
        }
    """
    name = "program.sequence"

    body = region_def("single_block")

    assembly_format = "$body attr-dict"
    
    traits = traits_def(NoTerminator())

    def verify_(self) -> None:
        # body 必须有且只有一个 block
        if len(self.body.blocks) != 1:
            raise ValueError("Sequence body must have exactly one block")

        # block 不能为空
        if len(list(self.body.blocks[0].ops)) == 0:
            raise ValueError("Sequence body cannot be empty")


@irdl_op_definition
class ForOp(IRDLOperation):
    """For 循环

    固定次数的循环，循环次数在编译时已知（可以是常量或编译时参数）。

    语法:
        program.for 100 {
            program.execute <1>
        }

    属性:
        count: IntegerAttr - 循环次数（必须 > 0）

    区域:
        body: single_block - 循环体

    示例:
        // 执行 100 次
        program.for 100 {
            program.execute <42>
        }

        // 嵌套循环
        program.for 5 {
            program.for 10 {
                program.execute <1>
            }
        }
    """
    name = "program.for"

    count: IntegerAttr = attr_def(IntegerAttr)
    body = region_def("single_block")

    assembly_format = "$count $body attr-dict"
    
    traits = traits_def(NoTerminator())

    def verify_(self) -> None:
        # 循环次数必须 > 0
        if self.count.value.data <= 0:
            raise ValueError(f"Loop count must be positive, got {self.count.value.data}")

        # body 必须有且只有一个 block
        if len(self.body.blocks) != 1:
            raise ValueError("Loop body must have exactly one block")


@irdl_op_definition
class IfOp(IRDLOperation):
    """条件分支（if-then-else）

    根据运行时条件选择执行分支。

    语法:
        program.if %cond {
            // then branch
            program.execute <1>
        } else {
            // else branch (optional)
            program.execute <2>
        }

    操作数:
        condition: ConditionType - 条件表达式

    区域:
        then_region: single_block - then 分支
        else_region: single_block - else 分支（可选）

    示例:
        // 带 else
        %cond = program.compare "adc_value", 500 : ">"
        program.if %cond {
            program.execute <1>
        } else {
            program.execute <2>
        }

        // 不带 else
        program.if %cond {
            program.execute <1>
        }
    """
    name = "program.if"

    condition = operand_def(ConditionType)
    then_region = region_def("single_block")
    else_region = region_def("single_block")
    
    traits = traits_def(NoTerminator())

    # 自定义 assembly format（支持可选的 else）
    def print(self, printer: Printer) -> None:
        printer.print_string(" ")
        printer.print_ssa_value(self.condition)
        printer.print_string(" ")
        printer.print_region(self.then_region)

        # else 分支是可选的
        if self.else_region.blocks and len(list(self.else_region.blocks[0].ops)) > 0:
            printer.print_string(" else ")
            printer.print_region(self.else_region)

        printer.print_op_attributes(self.attributes)

    def verify_(self) -> None:
        # then_region 必须存在
        if not self.then_region.blocks or len(self.then_region.blocks) != 1:
            raise ValueError("Then branch must have exactly one block")


# ============================================================================
# Operations - 条件表达式
# ============================================================================

@irdl_op_definition
class CompareOp(IRDLOperation):
    """比较操作（生成条件）

    将一个运行时变量与一个常量进行比较。

    语法:
        %cond = program.compare "var_name", 500 : ">" : !program.condition

    属性:
        var_ref: StringAttr - 变量名（引用 TCS 寄存器）
        comparator: StringAttr - 比较操作符（">", "<", ">=", "<=", "==", "!="）
        value: IntegerAttr - 比较值

    结果:
        result: ConditionType - 条件表达式

    示例:
        %cond1 = program.compare "adc_value", 500 : ">"
        %cond2 = program.compare "counter", 100 : "<="
    """
    name = "program.compare"

    var_ref: StringAttr = attr_def(StringAttr)
    comparator: StringAttr = attr_def(StringAttr)
    value: IntegerAttr = attr_def(IntegerAttr)

    result = result_def(ConditionType)

    assembly_format = '$var_ref `,` $value `:` $comparator attr-dict `:` type($result)'

    def verify_(self) -> None:
        # 验证比较操作符
        valid_ops = {">", "<", ">=", "<=", "==", "!="}
        if self.comparator.data not in valid_ops:
            raise ValueError(f"Invalid comparator: {self.comparator.data}")


@irdl_op_definition
class LogicalAndOp(IRDLOperation):
    """逻辑与（&&）

    语法:
        %result = program.and %cond1, %cond2 : !program.condition

    操作数:
        lhs: ConditionType - 左操作数
        rhs: ConditionType - 右操作数

    结果:
        result: ConditionType - 结果条件

    示例:
        %cond1 = program.compare "x", 100 : ">"
        %cond2 = program.compare "y", 200 : "<"
        %result = program.and %cond1, %cond2
    """
    name = "program.and"

    lhs = operand_def(ConditionType)
    rhs = operand_def(ConditionType)
    result = result_def(ConditionType)

    assembly_format = '$lhs `,` $rhs attr-dict `:` type($result)'


@irdl_op_definition
class LogicalOrOp(IRDLOperation):
    """逻辑或（||）

    语法:
        %result = program.or %cond1, %cond2 : !program.condition
    """
    name = "program.or"

    lhs = operand_def(ConditionType)
    rhs = operand_def(ConditionType)
    result = result_def(ConditionType)

    assembly_format = '$lhs `,` $rhs attr-dict `:` type($result)'


@irdl_op_definition
class LogicalNotOp(IRDLOperation):
    """逻辑非（!）

    语法:
        %result = program.not %cond : !program.condition

    操作数:
        operand: ConditionType - 输入条件

    结果:
        result: ConditionType - 否定后的条件

    示例:
        %cond = program.compare "flag", 1 : "=="
        %not_cond = program.not %cond
    """
    name = "program.not"

    operand = operand_def(ConditionType)
    result = result_def(ConditionType)

    assembly_format = '$operand attr-dict `:` type($result)'


# ============================================================================
# Dialect 定义
# ============================================================================

ProgramDialect = Dialect(
    "program",
    [
        # Control flow operations
        ExecuteOp,
        SequenceOp,
        ForOp,
        IfOp,
        # Condition operations
        CompareOp,
        LogicalAndOp,
        LogicalOrOp,
        LogicalNotOp,
    ],
    [
        # Types
        MorphismRefType,
        ConditionType,
        LoopVarType,
    ],
)
