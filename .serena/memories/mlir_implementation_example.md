# CatSeq MLIR 实现示例

## 项目结构

```
catseq/
├── mlir/                      # 新增 MLIR 实现
│   ├── __init__.py
│   ├── dialects/              # Dialect 定义
│   │   ├── __init__.py
│   │   ├── catseq.py         # catseq dialect
│   │   ├── qctrl.py          # qctrl dialect
│   │   └── rtmq.py           # rtmq dialect
│   ├── transforms/            # Lowering passes
│   │   ├── __init__.py
│   │   ├── catseq_to_qctrl.py
│   │   ├── qctrl_to_rtmq.py
│   │   └── optimizations.py
│   ├── codegen/               # 代码生成
│   │   ├── __init__.py
│   │   └── rtmq_emitter.py
│   └── compiler.py            # MLIR 编译器入口
├── compilation/               # 现有编译器（保持兼容）
└── ...
```

## 示例 1: catseq Dialect 定义

**文件**: `catseq/mlir/dialects/catseq.py`

```python
"""CatSeq Dialect - High-level Monoidal Category abstraction"""

from xdsl.ir import Dialect, Attribute, ParametrizedAttribute, Data
from xdsl.irdl import (
    irdl_attr_definition, irdl_op_definition, 
    IRDLOperation, AttrDef, ParameterDef,
    operand_def, result_def, attr_def
)
from xdsl.dialects.builtin import StringAttr, IntAttr, DictAttr
from xdsl.parser import Parser
from xdsl.printer import Printer
from dataclasses import dataclass
from typing import Annotated

# ============================================================================
# Types / Attributes
# ============================================================================

@irdl_attr_definition
class ChannelAttr(ParametrizedAttribute):
    """通道属性: #catseq.channel<"RWG_0", 0, "ttl">"""
    name = "catseq.channel"
    
    board_id: ParameterDef[StringAttr]
    local_id: ParameterDef[IntAttr]
    channel_type: ParameterDef[StringAttr]
    
    @staticmethod
    def parse_parameters(parser: Parser) -> list[Attribute]:
        parser.parse_punctuation("<")
        board_id = parser.parse_attribute()
        parser.parse_punctuation(",")
        local_id = parser.parse_attribute()
        parser.parse_punctuation(",")
        channel_type = parser.parse_attribute()
        parser.parse_punctuation(">")
        return [board_id, local_id, channel_type]
    
    def print_parameters(self, printer: Printer) -> None:
        printer.print_string("<")
        printer.print_attribute(self.board_id)
        printer.print_string(", ")
        printer.print_attribute(self.local_id)
        printer.print_string(", ")
        printer.print_attribute(self.channel_type)
        printer.print_string(">")

@irdl_attr_definition
class StateAttr(ParametrizedAttribute):
    """状态属性: #catseq.state<channel, {data}>"""
    name = "catseq.state"
    
    channel: ParameterDef[ChannelAttr]
    state_data: ParameterDef[DictAttr]
    
    @staticmethod
    def parse_parameters(parser: Parser) -> list[Attribute]:
        parser.parse_punctuation("<")
        channel = parser.parse_attribute()
        parser.parse_punctuation(",")
        state_data = parser.parse_attribute()
        parser.parse_punctuation(">")
        return [channel, state_data]
    
    def print_parameters(self, printer: Printer) -> None:
        printer.print_string("<")
        printer.print_attribute(self.channel)
        printer.print_string(", ")
        printer.print_attribute(self.state_data)
        printer.print_string(">")

@irdl_attr_definition
class MorphismType(ParametrizedAttribute):
    """Morphism 类型: !catseq.morphism<domain, codomain, duration>"""
    name = "catseq.morphism"
    
    domain: ParameterDef[StateAttr]
    codomain: ParameterDef[StateAttr]
    duration_cycles: ParameterDef[IntAttr]

# ============================================================================
# Operations
# ============================================================================

@irdl_op_definition
class ComposOp(IRDLOperation):
    """串行组合操作: @ 
    
    Example:
      %result = catseq.compos %lhs, %rhs : !catseq.morphism<...>
    """
    name = "catseq.compos"
    
    lhs: Annotated[operand_def, MorphismType]
    rhs: Annotated[operand_def, MorphismType]
    result: Annotated[result_def, MorphismType]
    
    def __init__(self, lhs, rhs):
        # 验证状态匹配
        lhs_type = lhs.type
        rhs_type = rhs.type
        
        if lhs_type.codomain != rhs_type.domain:
            raise ValueError(
                f"State mismatch: {lhs_type.codomain} != {rhs_type.domain}"
            )
        
        # 计算结果类型
        result_duration = IntAttr(
            lhs_type.duration_cycles.data + rhs_type.duration_cycles.data
        )
        result_type = MorphismType([
            lhs_type.domain,
            rhs_type.codomain,
            result_duration
        ])
        
        super().__init__(operands=[lhs, rhs], result_types=[result_type])
    
    assembly_format = "$lhs `,` $rhs attr-dict `:` type($result)"

@irdl_op_definition
class TensorOp(IRDLOperation):
    """张量积操作: |
    
    Example:
      %result = catseq.tensor %lhs, %rhs : !catseq.morphism<...>
    """
    name = "catseq.tensor"
    
    lhs: Annotated[operand_def, MorphismType]
    rhs: Annotated[operand_def, MorphismType]
    result: Annotated[result_def, MorphismType]
    
    def __init__(self, lhs, rhs):
        # TODO: 验证通道不重叠
        # TODO: 计算合并后的 domain/codomain
        
        lhs_type = lhs.type
        rhs_type = rhs.type
        
        # 时长取最大值
        result_duration = IntAttr(
            max(lhs_type.duration_cycles.data, rhs_type.duration_cycles.data)
        )
        
        # 简化：直接使用 lhs 的状态（实际需要合并）
        result_type = MorphismType([
            lhs_type.domain,
            lhs_type.codomain,
            result_duration
        ])
        
        super().__init__(operands=[lhs, rhs], result_types=[result_type])
    
    assembly_format = "$lhs `,` $rhs attr-dict `:` type($result)"

@irdl_op_definition
class AtomicOp(IRDLOperation):
    """原子操作
    
    Example:
      %result = catseq.atomic<"ttl_on"> %channel {duration = 1, params = {...}}
    """
    name = "catseq.atomic"
    
    operation_type: Annotated[attr_def, StringAttr]
    channel: Annotated[attr_def, ChannelAttr]
    duration: Annotated[attr_def, IntAttr]
    parameters: Annotated[attr_def, DictAttr]
    
    result: Annotated[result_def, MorphismType]
    
    def __init__(
        self, 
        operation_type: str,
        channel: ChannelAttr,
        duration: int,
        parameters: dict = None
    ):
        # 构造状态
        # TODO: 根据 operation_type 推导实际状态
        state_data = DictAttr(parameters or {})
        domain = StateAttr([channel, state_data])
        codomain = StateAttr([channel, state_data])
        
        result_type = MorphismType([
            domain,
            codomain,
            IntAttr(duration)
        ])
        
        super().__init__(
            attributes={
                "operation_type": StringAttr(operation_type),
                "channel": channel,
                "duration": IntAttr(duration),
                "parameters": state_data,
            },
            result_types=[result_type]
        )

@irdl_op_definition
class IdentityOp(IRDLOperation):
    """Identity morphism
    
    Example:
      %result = catseq.identity %channel {duration = 2500}
    """
    name = "catseq.identity"
    
    channel: Annotated[attr_def, ChannelAttr]
    state: Annotated[attr_def, StateAttr]
    duration: Annotated[attr_def, IntAttr]
    
    result: Annotated[result_def, MorphismType]
    
    def __init__(self, channel: ChannelAttr, state: StateAttr, duration: int):
        result_type = MorphismType([
            state,
            state,
            IntAttr(duration)
        ])
        
        super().__init__(
            attributes={
                "channel": channel,
                "state": state,
                "duration": IntAttr(duration),
            },
            result_types=[result_type]
        )

# ============================================================================
# Dialect
# ============================================================================

CatseqDialect = Dialect(
    "catseq",
    [
        # Operations
        ComposOp,
        TensorOp,
        AtomicOp,
        IdentityOp,
    ],
    [
        # Attributes/Types
        ChannelAttr,
        StateAttr,
        MorphismType,
    ]
)
```

## 示例 2: Morphism → catseq IR 转换

**文件**: `catseq/mlir/compiler.py`

```python
"""MLIR-based compiler entry point"""

from xdsl.context import MLContext
from xdsl.ir import Block, Region, Module as MLIRModule
from xdsl.builder import Builder, ImplicitBuilder
from xdsl.dialects.builtin import ModuleOp

from ..morphism import Morphism
from ..types.common import AtomicMorphism, OperationType
from .dialects.catseq import (
    CatseqDialect, ComposOp, TensorOp, AtomicOp, 
    ChannelAttr, StateAttr
)

def morphism_to_catseq_ir(morphism: Morphism) -> MLIRModule:
    """将 Morphism 转换为 catseq dialect IR"""
    
    ctx = MLContext()
    ctx.load_dialect(CatseqDialect)
    
    # 创建模块
    with ImplicitBuilder(ctx) as builder:
        module = ModuleOp([])
        
        # 转换 Morphism
        morphism_value = convert_morphism(morphism, builder)
        
        # 将顶层 morphism 作为模块的主体
        # TODO: 需要设计顶层容器操作
        
    return module

def convert_morphism(morphism: Morphism, builder: Builder):
    """递归转换 Morphism 到 IR"""
    
    # 如果是原子操作
    if len(morphism.lanes) == 1:
        channel, lane = next(iter(morphism.lanes.items()))
        if len(lane.operations) == 1:
            op = lane.operations[0]
            return convert_atomic(op, builder)
    
    # TODO: 处理复合 Morphism
    # 需要分析 Morphism 的组合结构（@ 还是 |）
    # 这需要在 Morphism 类中记录组合信息
    
    raise NotImplementedError("Complex morphism conversion")

def convert_atomic(atomic: AtomicMorphism, builder: Builder):
    """转换原子操作"""
    
    # 创建 ChannelAttr
    channel_attr = ChannelAttr([
        StringAttr(atomic.channel.board.id),
        IntAttr(atomic.channel.local_id),
        StringAttr(atomic.channel.channel_type.name.lower())
    ])
    
    # 创建 StateAttr
    state_data = DictAttr({})  # TODO: 从 atomic.start_state 提取
    state_attr = StateAttr([channel_attr, state_data])
    
    # 根据操作类型创建对应的 Op
    if atomic.operation_type == OperationType.IDENTITY:
        return IdentityOp(
            channel=channel_attr,
            state=state_attr,
            duration=atomic.duration_cycles
        )
    else:
        op_type_str = atomic.operation_type.name.lower()
        return AtomicOp(
            operation_type=op_type_str,
            channel=channel_attr,
            duration=atomic.duration_cycles,
            parameters={}  # TODO: 提取参数
        )

# 使用示例
if __name__ == "__main__":
    from catseq import ttl_on, ttl_off, identity
    from catseq.types.common import Board, Channel, ChannelType
    
    # 构建 Morphism
    board = Board("RWG_0")
    ch = Channel(board, 0, ChannelType.TTL)
    
    pulse = ttl_on(ch) @ identity(ch, 10e-6) @ ttl_off(ch)
    
    # 转换为 MLIR
    module = morphism_to_catseq_ir(pulse)
    print(module)
```

## 示例 3: catseq → qctrl Lowering Pass

**文件**: `catseq/mlir/transforms/catseq_to_qctrl.py`

```python
"""Lowering pass: catseq dialect → qctrl dialect"""

from xdsl.pattern_rewriter import (
    RewritePattern, PatternRewriter, 
    op_type_rewrite_pattern,
    GreedyRewritePatternApplier
)
from xdsl.ir import Operation, SSAValue

from ..dialects.catseq import ComposOp, AtomicOp, IdentityOp
from ..dialects.qctrl import TTLSetOp, WaitOp, SequenceOp

class LowerAtomicToQctrlPattern(RewritePattern):
    """将 catseq.atomic 转换为 qctrl 操作"""
    
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: AtomicOp, rewriter: PatternRewriter):
        op_type = op.operation_type.data
        channel = op.channel
        board = channel.board_id.data
        local_id = channel.local_id.data
        
        if op_type == "ttl_on":
            # TTL ON: mask = 1 << local_id, state = mask
            mask = 1 << local_id
            state = mask
            timestamp = 0  # TODO: 从上下文计算
            
            new_op = TTLSetOp(
                board=board,
                channel_mask=mask,
                state_mask=state,
                timestamp=timestamp
            )
            rewriter.replace_matched_op(new_op)
            
        elif op_type == "ttl_off":
            # TTL OFF: mask = 1 << local_id, state = 0
            mask = 1 << local_id
            state = 0
            timestamp = 0
            
            new_op = TTLSetOp(
                board=board,
                channel_mask=mask,
                state_mask=state,
                timestamp=timestamp
            )
            rewriter.replace_matched_op(new_op)
        
        # TODO: 处理其他操作类型

class LowerIdentityToWaitPattern(RewritePattern):
    """将 catseq.identity 转换为 qctrl.wait"""
    
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: IdentityOp, rewriter: PatternRewriter):
        duration = op.duration.data
        
        wait_op = WaitOp(cycles=duration)
        rewriter.replace_matched_op(wait_op)

class LowerComposToSequencePattern(RewritePattern):
    """将 catseq.compos 展开为线性序列"""
    
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: ComposOp, rewriter: PatternRewriter):
        # 递归展开左右操作数
        lhs_ops = self.extract_operations(op.lhs)
        rhs_ops = self.extract_operations(op.rhs)
        
        # 调整右侧时间戳
        lhs_duration = self.get_duration(op.lhs)
        rhs_ops_adjusted = self.adjust_timestamps(rhs_ops, lhs_duration)
        
        # 合并
        all_ops = lhs_ops + rhs_ops_adjusted
        
        # TODO: 创建 SequenceOp 包装
        rewriter.replace_matched_op(all_ops)
    
    def extract_operations(self, value: SSAValue) -> list[Operation]:
        """提取 SSA value 对应的操作列表"""
        # TODO: 实现提取逻辑
        return []
    
    def get_duration(self, value: SSAValue) -> int:
        """获取 morphism 的时长"""
        morphism_type = value.type
        return morphism_type.duration_cycles.data
    
    def adjust_timestamps(self, ops: list[Operation], offset: int) -> list[Operation]:
        """调整操作的时间戳"""
        # TODO: 实现时间戳调整
        return ops

# 应用 lowering
def lower_catseq_to_qctrl(module):
    """应用 catseq → qctrl lowering pass"""
    patterns = [
        LowerAtomicToQctrlPattern(),
        LowerIdentityToWaitPattern(),
        LowerComposToSequencePattern(),
    ]
    
    applier = GreedyRewritePatternApplier(patterns)
    applier.rewrite_module(module)
```

## 示例 4: qctrl Dialect 定义（简化版）

**文件**: `catseq/mlir/dialects/qctrl.py`

```python
"""Quantum Control Dialect - Mid-level hardware operations"""

from xdsl.ir import Dialect
from xdsl.irdl import irdl_op_definition, IRDLOperation, attr_def
from xdsl.dialects.builtin import StringAttr, IntAttr
from typing import Annotated

@irdl_op_definition
class TTLSetOp(IRDLOperation):
    """TTL 状态设置
    
    Example:
      qctrl.ttl_set "rwg_0", 0x01, 0x01 at 0
    """
    name = "qctrl.ttl_set"
    
    board: Annotated[attr_def, StringAttr]
    channel_mask: Annotated[attr_def, IntAttr]
    state_mask: Annotated[attr_def, IntAttr]
    timestamp: Annotated[attr_def, IntAttr]
    
    def __init__(self, board: str, channel_mask: int, state_mask: int, timestamp: int):
        super().__init__(attributes={
            "board": StringAttr(board),
            "channel_mask": IntAttr(channel_mask),
            "state_mask": IntAttr(state_mask),
            "timestamp": IntAttr(timestamp),
        })

@irdl_op_definition
class WaitOp(IRDLOperation):
    """等待操作
    
    Example:
      qctrl.wait 2500
    """
    name = "qctrl.wait"
    
    cycles: Annotated[attr_def, IntAttr]
    
    def __init__(self, cycles: int):
        super().__init__(attributes={
            "cycles": IntAttr(cycles)
        })

@irdl_op_definition
class SequenceOp(IRDLOperation):
    """时序序列容器
    
    Example:
      qctrl.sequence @"rwg_0" {
        qctrl.ttl_set ...
        qctrl.wait ...
      }
    """
    name = "qctrl.sequence"
    
    board_id: Annotated[attr_def, StringAttr]
    body: region_def()
    
    def __init__(self, board_id: str, body):
        super().__init__(
            attributes={"board_id": StringAttr(board_id)},
            regions=[body]
        )

QctrlDialect = Dialect(
    "qctrl",
    [TTLSetOp, WaitOp, SequenceOp],
    []
)
```

## 使用流程

```python
from catseq import ttl_on, ttl_off, identity
from catseq.types.common import Board, Channel, ChannelType
from catseq.mlir.compiler import morphism_to_catseq_ir
from catseq.mlir.transforms.catseq_to_qctrl import lower_catseq_to_qctrl

# 1. 构建 Morphism (现有 API)
board = Board("RWG_0")
ch = Channel(board, 0, ChannelType.TTL)
pulse = ttl_on(ch) @ identity(ch, 10e-6) @ ttl_off(ch)

# 2. 转换为 catseq IR
module = morphism_to_catseq_ir(pulse)
print("=== catseq IR ===")
print(module)

# 3. Lowering 到 qctrl
lower_catseq_to_qctrl(module)
print("\n=== qctrl IR ===")
print(module)

# 4. 继续 lowering 到 rtmq ...
# 5. 代码生成 ...
```

## 下一步实现建议

### 立即可做的

1. **实现基础 catseq dialect**
   - 定义基本的 type 和 op
   - 实现简单的打印和解析

2. **实现 Morphism → IR 转换**
   - 从现有的 Morphism 数据结构提取信息
   - 生成 catseq IR

3. **实现一个简单的 lowering pass**
   - AtomicOp → qctrl 操作
   - 验证基本流程可行

### 需要设计决策的

1. **Morphism 结构信息**
   - 当前 Morphism 类不记录组合方式（@ 还是 |）
   - 需要扩展 Morphism 或在转换时推断

2. **时间戳管理**
   - 在哪个层次引入绝对时间戳？
   - catseq 层使用相对时间，qctrl 层使用绝对时间

3. **状态表示**
   - 如何在 MLIR 中表示复杂的状态（RWGActive 等）？
   - 使用 DictAttr 还是定义专门的 Attribute？

4. **Region 设计**
   - qctrl.sequence 如何组织内部操作？
   - 是否需要 Block 和 CFG？
