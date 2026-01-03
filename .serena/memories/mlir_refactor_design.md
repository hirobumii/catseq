# CatSeq MLIR 重构设计方案

## 设计目标

将当前的五阶段直接编译架构重构为基于 MLIR/xDSL 的分层编译架构，实现：

1. **更好的模块化**: 清晰的 IR 层次和转换边界
2. **可扩展性**: 易于添加新硬件支持和优化
3. **可验证性**: 每个 IR 层次都可以独立验证
4. **优化能力**: 利用 MLIR 的优化框架

## 三层 Dialect 架构

```
┌─────────────────────────────────────┐
│  catseq dialect (高层抽象)           │
│  - Morphism 组合                     │
│  - Monoidal Category 语义            │
└──────────────┬──────────────────────┘
               │ Lowering Pass 1
               ↓
┌─────────────────────────────────────┐
│  qctrl dialect (量子控制中层)         │
│  - 硬件操作 (TTL, RWG, RSP)          │
│  - 时序约束和调度                     │
└──────────────┬──────────────────────┘
               │ Lowering Pass 2
               ↓
┌─────────────────────────────────────┐
│  rtmq dialect (RTMQ 硬件层)          │
│  - RTMQ 指令 (AMK, SFS, Timer)       │
│  - CSR 访问                          │
└──────────────┬──────────────────────┘
               │ Code Generation
               ↓
         OASM DSL / 汇编
```

## Layer 1: catseq Dialect (高层抽象)

### 核心 Types

```python
from xdsl.irdl import irdl_attr_definition, AttrDef
from xdsl.ir import Attribute, ParameterDef

@irdl_attr_definition
class ChannelType(Attribute):
    """通道类型: !catseq.channel<board_id, local_id, type>"""
    name = "catseq.channel"
    
    board_id: ParameterDef[StringAttr]
    local_id: ParameterDef[IntAttr]
    channel_type: ParameterDef[StringAttr]  # "ttl", "rwg", "rsp"

@irdl_attr_definition
class StateType(Attribute):
    """状态类型: !catseq.state<channel, state_data>"""
    name = "catseq.state"
    
    channel: ParameterDef[ChannelType]
    state_data: ParameterDef[DictAttr]  # 状态具体数据

@irdl_attr_definition
class MorphismType(Attribute):
    """Morphism 类型: !catseq.morphism<domain, codomain, duration>"""
    name = "catseq.morphism"
    
    domain: ParameterDef[StateType]      # 起始状态
    codomain: ParameterDef[StateType]    # 结束状态
    duration_cycles: ParameterDef[IntAttr]
```

### 核心 Operations

```python
from xdsl.irdl import irdl_op_definition, IRDLOperation, operand_def, result_def, attr_def

@irdl_op_definition
class ComposOp(IRDLOperation):
    """串行组合: @ 操作符
    
    %result = catseq.compos %lhs, %rhs : !catseq.morphism<...>
    """
    name = "catseq.compos"
    
    lhs = operand_def(MorphismType)
    rhs = operand_def(MorphismType)
    result = result_def(MorphismType)
    
    # 验证状态匹配
    def verify_(self):
        if self.lhs.type.codomain != self.rhs.type.domain:
            raise VerifyException("State mismatch in composition")

@irdl_op_definition
class TensorOp(IRDLOperation):
    """并行组合: | 操作符 (张量积)
    
    %result = catseq.tensor %lhs, %rhs : !catseq.morphism<...>
    """
    name = "catseq.tensor"
    
    lhs = operand_def(MorphismType)
    rhs = operand_def(MorphismType)
    result = result_def(MorphismType)
    
    def verify_(self):
        # 验证通道不重叠
        lhs_channels = extract_channels(self.lhs)
        rhs_channels = extract_channels(self.rhs)
        if lhs_channels & rhs_channels:
            raise VerifyException("Overlapping channels in tensor product")

@irdl_op_definition
class IdentityOp(IRDLOperation):
    """Identity morphism
    
    %result = catseq.identity %duration : !catseq.morphism<...>
    """
    name = "catseq.identity"
    
    channel = attr_def(ChannelType)
    state = attr_def(StateType)
    duration = attr_def(IntAttr)
    result = result_def(MorphismType)

@irdl_op_definition
class AtomicOp(IRDLOperation):
    """原子操作（TTL_ON, TTL_OFF 等）
    
    %result = catseq.atomic<"ttl_on"> %channel : !catseq.morphism<...>
    """
    name = "catseq.atomic"
    
    operation_type = attr_def(StringAttr)  # "ttl_on", "ttl_off", "rwg_set_carrier"
    channel = operand_def(ChannelType)
    duration = attr_def(IntAttr)
    parameters = attr_def(DictAttr)  # 操作参数
    result = result_def(MorphismType)
```

### 示例 IR

```mlir
// ttl_on(ch1) @ identity(ch1, 10us) @ ttl_off(ch1)

%ch1 = catseq.channel<"RWG_0", 0, "ttl">

%ttl_on = catseq.atomic<"ttl_on"> %ch1 {duration = 1} : !catseq.morphism<...>
%wait = catseq.identity %ch1 {duration = 2500} : !catseq.morphism<...>
%ttl_off = catseq.atomic<"ttl_off"> %ch1 {duration = 1} : !catseq.morphism<...>

%seq1 = catseq.compos %ttl_on, %wait : !catseq.morphism<...>
%pulse = catseq.compos %seq1, %ttl_off : !catseq.morphism<...>
```

## Layer 2: qctrl Dialect (量子控制)

### 核心 Operations

```python
@irdl_op_definition
class TTLSetOp(IRDLOperation):
    """TTL 状态设置
    
    qctrl.ttl_set %board, %mask, %state at %timestamp
    """
    name = "qctrl.ttl_set"
    
    board = attr_def(StringAttr)
    channel_mask = attr_def(IntAttr)
    state_mask = attr_def(IntAttr)
    timestamp = attr_def(IntAttr)  # 绝对时间戳

@irdl_op_definition
class WaitOp(IRDLOperation):
    """等待操作
    
    qctrl.wait %cycles
    """
    name = "qctrl.wait"
    
    cycles = attr_def(IntAttr)

@irdl_op_definition
class RWGLoadOp(IRDLOperation):
    """RWG 加载波形
    
    qctrl.rwg_load %board, %channel, %params at %timestamp
    """
    name = "qctrl.rwg_load"
    
    board = attr_def(StringAttr)
    channel = attr_def(IntAttr)
    waveform_params = attr_def(DictAttr)
    timestamp = attr_def(IntAttr)

@irdl_op_definition
class RWGPlayOp(IRDLOperation):
    """RWG 播放波形
    
    qctrl.rwg_play %board, %pud_mask, %iou_mask at %timestamp
    """
    name = "qctrl.rwg_play"
    
    board = attr_def(StringAttr)
    pud_mask = attr_def(IntAttr)
    iou_mask = attr_def(IntAttr)
    timestamp = attr_def(IntAttr)

@irdl_op_definition
class SequenceOp(IRDLOperation):
    """时序序列容器（包含 region）
    
    qctrl.sequence @board_id {
      ^bb0:
        qctrl.ttl_set ...
        qctrl.wait ...
        qctrl.ttl_set ...
    }
    """
    name = "qctrl.sequence"
    
    board_id = attr_def(StringAttr)
    body = region_def()
```

### 示例 IR

```mlir
// Lowered from catseq dialect
qctrl.sequence @"rwg_0" {
^bb0:
  qctrl.ttl_set "rwg_0", 0x01, 0x01 at 0
  qctrl.wait 2500
  qctrl.ttl_set "rwg_0", 0x01, 0x00 at 2501
}
```

## Layer 3: rtmq Dialect (硬件层)

### 核心 Operations

```python
@irdl_op_definition
class AMKOp(IRDLOperation):
    """AMK 指令 (AND-MASK-OR)
    
    rtmq.amk %csr_name, %mask, %value
    """
    name = "rtmq.amk"
    
    csr_name = attr_def(StringAttr)
    mask = attr_def(StringAttr)      # RTMQ 格式 "3.0"
    value = attr_def(StringAttr)     # RTMQ 格式 "$01"

@irdl_op_definition
class SFSOp(IRDLOperation):
    """SFS 指令 (子文件选择)
    
    rtmq.sfs %module, %subfile
    """
    name = "rtmq.sfs"
    
    module = attr_def(StringAttr)
    subfile = attr_def(StringAttr)

@irdl_op_definition
class TimerOp(IRDLOperation):
    """Timer 设置和等待
    
    rtmq.timer %cycles
    """
    name = "rtmq.timer"
    
    cycles = attr_def(IntAttr)

@irdl_op_definition
class NOPOp(IRDLOperation):
    """NOP 指令
    
    rtmq.nop %count
    """
    name = "rtmq.nop"
    
    count = attr_def(IntAttr)
```

### 示例 IR

```mlir
// Lowered from qctrl dialect
rtmq.amk "ttl", "1.0", "$01"
rtmq.timer 2500
rtmq.amk "ttl", "1.0", "$00"
```

## Lowering Passes

### Pass 1: catseq → qctrl

**目标**: 将 Morphism 组合展开为时间序列操作

```python
from xdsl.pattern_rewriter import RewritePattern, PatternRewriter, op_type_rewrite_pattern

class LowerComposPattern(RewritePattern):
    """将 catseq.compos 展开为线性序列"""
    
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: ComposOp, rewriter: PatternRewriter):
        # 提取左右操作数的时间序列
        lhs_ops = extract_operations(op.lhs)
        rhs_ops = extract_operations(op.rhs)
        
        # 调整右侧时间戳
        lhs_duration = op.lhs.type.duration_cycles
        rhs_ops_adjusted = adjust_timestamps(rhs_ops, offset=lhs_duration)
        
        # 合并为单一序列
        merged = lhs_ops + rhs_ops_adjusted
        rewriter.replace_matched_op(merged)

class LowerAtomicPattern(RewritePattern):
    """将 catseq.atomic 转换为 qctrl 操作"""
    
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: AtomicOp, rewriter: PatternRewriter):
        match op.operation_type.data:
            case "ttl_on":
                board = op.channel.board_id
                mask = 1 << op.channel.local_id
                state = mask
                new_op = TTLSetOp(board, mask, state, timestamp=0)
                rewriter.replace_matched_op(new_op)
            
            case "ttl_off":
                board = op.channel.board_id
                mask = 1 << op.channel.local_id
                state = 0
                new_op = TTLSetOp(board, mask, state, timestamp=0)
                rewriter.replace_matched_op(new_op)
            
            case "rwg_set_carrier":
                # 转换为 RWG 操作
                ...

class MergeTensorPattern(RewritePattern):
    """合并并行操作"""
    
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: TensorOp, rewriter: PatternRewriter):
        # 提取两个分支的操作
        lhs_ops = extract_operations(op.lhs)
        rhs_ops = extract_operations(op.rhs)
        
        # 按板卡分组
        ops_by_board = group_by_board(lhs_ops + rhs_ops)
        
        # 对每个板卡创建 sequence
        sequences = []
        for board, ops in ops_by_board.items():
            seq = SequenceOp(board_id=board, body=Region([Block(ops)]))
            sequences.append(seq)
        
        rewriter.replace_matched_op(sequences)
```

### Pass 2: qctrl → rtmq

**目标**: 将量子控制操作转换为 RTMQ 指令

```python
class LowerTTLSetPattern(RewritePattern):
    """TTL 设置 → AMK 指令"""
    
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: TTLSetOp, rewriter: PatternRewriter):
        # 转换掩码格式
        rtmq_mask = binary_to_rtmq_mask(op.channel_mask)
        rtmq_state = binary_to_rtmq_mask(op.state_mask)
        
        # 生成 AMK 指令
        amk = AMKOp(csr_name="ttl", mask=rtmq_mask, value=rtmq_state)
        rewriter.replace_matched_op(amk)

class LowerWaitPattern(RewritePattern):
    """Wait → Timer/NOP"""
    
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: WaitOp, rewriter: PatternRewriter):
        cycles = op.cycles.data
        
        if cycles <= 4:
            # 短延迟用 NOP
            new_op = NOPOp(count=cycles)
        else:
            # 长延迟用 Timer
            new_op = TimerOp(cycles=cycles)
        
        rewriter.replace_matched_op(new_op)

class LowerRWGPattern(RewritePattern):
    """RWG 操作 → RTMQ 指令序列"""
    
    @op_type_rewrite_pattern
    def match_and_rewrite(self, op: RWGLoadOp, rewriter: PatternRewriter):
        # 生成 FTE.cfg, RWG.frq, RWG.amp 等指令
        instructions = [
            # FTE configuration
            AMKOp(...),
            # Frequency coefficients
            AMKOp(...),
            # Amplitude coefficients
            AMKOp(...),
        ]
        rewriter.replace_matched_op(instructions)
```

### Pass 3: 优化 Passes

```python
class MergeConsecutiveTTLPattern(RewritePattern):
    """合并连续的 TTL 操作"""
    
    def match_and_rewrite(self, op: TTLSetOp, rewriter: PatternRewriter):
        # 查找下一个 TTL 操作
        next_op = find_next_ttl_set(op)
        if not next_op or next_op.board != op.board:
            return
        
        # 合并掩码
        merged_mask = op.channel_mask | next_op.channel_mask
        merged_state = (op.state_mask & op.channel_mask) | \
                       (next_op.state_mask & next_op.channel_mask)
        
        # 创建合并后的操作
        merged = TTLSetOp(op.board, merged_mask, merged_state, op.timestamp)
        rewriter.replace_matched_op([merged], erase_old_ops=[op, next_op])

class ScheduleRWGLoadPattern(RewritePattern):
    """优化 RWG load-play 调度"""
    
    def match_and_rewrite(self, seq: SequenceOp, rewriter: PatternRewriter):
        # 识别 load-play 对
        pairs = identify_load_play_pairs(seq.body)
        
        # 计算最优调度
        for load_op, play_op in pairs:
            optimal_time = calculate_optimal_load_time(load_op, play_op)
            load_op.timestamp = optimal_time
```

## 代码生成

### RTMQ → OASM DSL

```python
class RTMQToOASMEmitter:
    """将 RTMQ dialect IR 转换为 OASM DSL 调用"""
    
    def emit_module(self, module: Module) -> List[OASMCall]:
        calls = []
        for op in module.walk():
            if isinstance(op, AMKOp):
                calls.append(self.emit_amk(op))
            elif isinstance(op, TimerOp):
                calls.append(self.emit_timer(op))
            elif isinstance(op, NOPOp):
                calls.append(self.emit_nop(op))
        return calls
    
    def emit_amk(self, op: AMKOp) -> OASMCall:
        return OASMCall(
            dsl_func=lambda: amk(op.csr_name, op.mask, op.value),
            args=()
        )
    
    def emit_timer(self, op: TimerOp) -> OASMCall:
        return OASMCall(
            dsl_func=wait_mu,
            args=(op.cycles.data,)
        )
```

## 完整编译流程

```python
from xdsl.context import MLContext
from xdsl.pattern_rewriter import GreedyRewritePatternApplier

def compile_morphism_to_oasm(morphism: Morphism) -> Dict[str, List[OASMCall]]:
    # 1. 将 Morphism 转换为 catseq dialect IR
    ctx = MLContext()
    ctx.load_dialect(CatseqDialect)
    ctx.load_dialect(QctrlDialect)
    ctx.load_dialect(RTMQDialect)
    
    module = morphism_to_catseq_ir(morphism, ctx)
    
    # 2. Lowering: catseq → qctrl
    catseq_to_qctrl_patterns = [
        LowerComposPattern(),
        LowerAtomicPattern(),
        MergeTensorPattern(),
    ]
    applier = GreedyRewritePatternApplier(catseq_to_qctrl_patterns)
    applier.rewrite_module(module)
    module.verify()
    
    # 3. 优化: qctrl level
    qctrl_opt_patterns = [
        MergeConsecutiveTTLPattern(),
        ScheduleRWGLoadPattern(),
    ]
    applier = GreedyRewritePatternApplier(qctrl_opt_patterns)
    applier.rewrite_module(module)
    
    # 4. Lowering: qctrl → rtmq
    qctrl_to_rtmq_patterns = [
        LowerTTLSetPattern(),
        LowerWaitPattern(),
        LowerRWGPattern(),
    ]
    applier = GreedyRewritePatternApplier(qctrl_to_rtmq_patterns)
    applier.rewrite_module(module)
    module.verify()
    
    # 5. 代码生成: rtmq → OASM
    emitter = RTMQToOASMEmitter()
    oasm_calls = emitter.emit_module(module)
    
    return group_by_board(oasm_calls)
```

## 优势总结

### 相比当前架构的改进

1. **清晰的抽象层次**
   - 每个 dialect 对应一个抽象级别
   - 便于理解和维护

2. **可验证性**
   - 每个 IR 层次都有类型系统和验证规则
   - 每次转换后都可以验证 IR 合法性

3. **优化能力**
   - 可以在不同层次插入优化 pass
   - 利用 MLIR 的成熟优化框架

4. **可扩展性**
   - 添加新硬件只需扩展 qctrl dialect
   - 添加新优化只需添加新 pattern

5. **调试友好**
   - 可以打印每个阶段的 IR
   - 便于定位问题

6. **工具链生态**
   - 可以利用 MLIR 的可视化工具
   - 可以与其他 MLIR dialect 集成

## 实现路线图

### Phase 1: 基础设施
- [ ] 定义 catseq dialect (types + ops)
- [ ] 定义 qctrl dialect
- [ ] 定义 rtmq dialect
- [ ] 实现 Morphism → catseq IR 转换

### Phase 2: Lowering Passes
- [ ] 实现 catseq → qctrl lowering
- [ ] 实现 qctrl → rtmq lowering
- [ ] 实现 RTMQ → OASM 代码生成

### Phase 3: 优化
- [ ] 实现基本优化 passes
- [ ] 实现 RWG 调度优化
- [ ] 实现跨板卡优化

### Phase 4: 集成和测试
- [ ] 集成到现有 API
- [ ] 迁移所有测试用例
- [ ] 性能对比和调优
