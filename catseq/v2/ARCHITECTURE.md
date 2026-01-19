# CatSeq V2 Architecture Design

## Overview

CatSeq V2 implements a three-layer MLIR/xDSL dialect architecture for compiling quantum control programs to RTMQ hardware. This document describes the complete architecture, design decisions, and implementation details.

**Version**: 0.3.0-dev
**Development Timeline**: 13 weeks (2026-01-18 to 2026-04-18)
**Location**: `catseq/v2/`

## Design Goals

1. **Modularity**: Clear IR layers with well-defined transformation boundaries
2. **Extensibility**: Easy to add new hardware support and optimizations
3. **Verifiability**: Each IR level can be independently validated
4. **Optimization**: Leverage MLIR's pattern rewriting framework
5. **Runtime Conditionals**: Native support for hardware-level conditional execution

## Three-Layer Dialect Architecture

```
┌─────────────────────────────────────────────────┐
│  Program API (Existing - Reused)                │
│  - Functional Monad interface                    │
│  - AST: MorphismStmt, SequenceStmt, ForLoopStmt │
│  - Runtime variables & conditions                │
└──────────────────┬──────────────────────────────┘
                   │ AST → program dialect IR (Existing)
                   ↓
┌─────────────────────────────────────────────────┐
│  program dialect (Existing - Reused)            │
│  - ExecuteOp, SequenceOp, ForOp, IfOp           │
│  - Morphism registry                             │
└──────────────────┬──────────────────────────────┘
                   │ Lowering Pass 1 (NEW)
                   ↓
┌─────────────────────────────────────────────────┐
│  catseq dialect (NEW - Layer 1)                 │
│  - Morphism composition (ComposOp, TensorOp)    │
│  - Monoidal Category semantics                  │
│  - Channel & State types                        │
└──────────────────┬──────────────────────────────┘
                   │ Lowering Pass 2 (NEW)
                   ↓
┌─────────────────────────────────────────────────┐
│  qctrl dialect (NEW - Layer 2)                  │
│  - Hardware operations: TTLSetOp, RWGLoadOp     │
│  - Timing constraints & scheduling              │
│  - CondBrOp for runtime conditionals            │
└──────────────────┬──────────────────────────────┘
                   │ Lowering Pass 3 (NEW)
                   ↓
┌─────────────────────────────────────────────────┐
│  rtmq dialect (NEW - Layer 3)                   │
│  - RTMQ instructions: AMKOp, SFSOp, TimerOp     │
│  - TCS register allocation                      │
│  - Conditional jumps: LSEOp, AMKPTROp           │
└──────────────────┬──────────────────────────────┘
                   │ Code Generation (NEW)
                   ↓
            OASM DSL Calls
```

## Layer 1: catseq Dialect

**Location**: `catseq/v2/dialects/catseq_dialect.py`

### Purpose
Represent Morphism-level composition operations with Category Theory semantics.

### Core Types

```python
!catseq.channel<board_id: string, local_id: int, type: string>
  # Example: !catseq.channel<"RWG_0", 0, "ttl">

!catseq.state<channel: !catseq.channel, state_data: dict>
  # Example: !catseq.state<!catseq.channel<"RWG_0", 0, "ttl">, {value: 1}>

!catseq.morphism<domain: !catseq.state, codomain: !catseq.state, duration: int>
  # Represents a state transformation over time
```

### Core Operations

1. **ComposOp** - Serial composition (@)
   ```
   %result = catseq.compos %lhs, %rhs : !catseq.morphism<...>
   ```
   - Verification: `lhs.codomain == rhs.domain` (state continuity)

2. **TensorOp** - Parallel composition (|)
   ```
   %result = catseq.tensor %lhs, %rhs : !catseq.morphism<...>
   ```
   - Verification: No overlapping channels

3. **IdentityOp** - Identity morphism
   ```
   %result = catseq.identity %channel, %duration : !catseq.morphism<...>
   ```

4. **AtomicOp** - Atomic operations
   ```
   %result = catseq.atomic<"ttl_on"> %channel {params: {...}} : !catseq.morphism<...>
   ```

### Example IR

```mlir
// ttl_on(ch1) @ wait(10us) @ ttl_off(ch1)
%ch1 = catseq.channel<"RWG_0", 0, "ttl">
%state_off = catseq.state<%ch1, {value: 0}>
%state_on = catseq.state<%ch1, {value: 1}>

%ttl_on = catseq.atomic<"ttl_on"> %ch1 {duration: 1} :
          !catseq.morphism<%state_off, %state_on, 1>

%wait = catseq.identity %ch1 {duration: 2500} :
        !catseq.morphism<%state_on, %state_on, 2500>

%ttl_off = catseq.atomic<"ttl_off"> %ch1 {duration: 1} :
           !catseq.morphism<%state_on, %state_off, 1>

%seq1 = catseq.compos %ttl_on, %wait : !catseq.morphism<...>
%pulse = catseq.compos %seq1, %ttl_off : !catseq.morphism<...>
```

## Layer 2: qctrl Dialect

**Location**: `catseq/v2/dialects/qctrl_dialect.py`

### Purpose
Represent quantum control operations with explicit timing and board-level resource management.

### Core Operations

1. **TTLSetOp** - TTL state setting
   ```
   qctrl.ttl_set %board, %mask, %state at %timestamp
   ```

2. **WaitOp** - Wait operation
   ```
   qctrl.wait %cycles
   ```

3. **RWGLoadOp** - RWG waveform loading
   ```
   qctrl.rwg_load %board, %channel, %params at %timestamp
   ```

4. **RWGPlayOp** - RWG waveform playback
   ```
   qctrl.rwg_play %board, %pud_mask, %iou_mask at %timestamp
   ```

5. **CondBrOp** - Conditional branch (CRITICAL for runtime conditionals)
   ```
   qctrl.cond_br %condition, ^then_block, ^else_block
   ```
   - Uses successor blocks (CFG-style control flow)
   - Supports runtime variables from TCS registers

6. **SequenceOp** - Timing sequence container
   ```
   qctrl.sequence @board_id {
     ^bb0:
       qctrl.ttl_set ...
       qctrl.wait ...
   }
   ```

### Example IR

```mlir
// TTL pulse after lowering from catseq
qctrl.sequence @"rwg_0" {
^bb0:
  qctrl.ttl_set "rwg_0", 0x01, 0x01 at 0      // Turn on
  qctrl.wait 2500                              // Wait 10us
  qctrl.ttl_set "rwg_0", 0x01, 0x00 at 2501   // Turn off
}
```

### Conditional Execution Example

```mlir
// if_then_else(adc_value > 500, pulse_high, pulse_low)
%cond = qctrl.compare %adc_value, ">", 500 : !qctrl.condition

qctrl.cond_br %cond, ^then_block, ^else_block

^then_block:
  qctrl.ttl_set "rwg_0", 0x01, 0x01 at 0
  qctrl.wait 1000
  qctrl.ttl_set "rwg_0", 0x01, 0x00 at 1001
  qctrl.br ^merge_block

^else_block:
  qctrl.ttl_set "rwg_0", 0x01, 0x01 at 0
  qctrl.wait 500
  qctrl.ttl_set "rwg_0", 0x01, 0x00 at 501
  qctrl.br ^merge_block

^merge_block:
  // Continue execution
```

## Layer 3: rtmq Dialect

**Location**: `catseq/v2/dialects/rtmq_dialect.py`

### Purpose
Represent RTMQ hardware-level instructions with precise cycle timing and register allocation.

### Core Operations

1. **AMKOp** - AMK instruction (AND-MASK-OR)
   ```
   rtmq.amk %csr_name, %mask, %value
   ```

2. **SFSOp** - Subfile selection
   ```
   rtmq.sfs %module, %subfile
   ```

3. **TimerOp** - Timer-based wait
   ```
   rtmq.timer %cycles
   ```

4. **NOPOp** - NOP instruction
   ```
   rtmq.nop %count
   ```

5. **LSEOp, EQUOp, NEQOp** - TCS comparison instructions
   ```
   rtmq.lse %dst, %src1, %src2  // dst = (src1 <= src2)
   rtmq.equ %dst, %src1, %src2  // dst = (src1 == src2)
   ```

6. **AMKPTROp** - Conditional/unconditional jump
   ```
   rtmq.amk_ptr %condition_reg, %target_label  // Conditional jump
   rtmq.amk_ptr "3.0", %target_label           // Unconditional jump
   ```

### TCS Register Allocation

The rtmq dialect includes a register allocator that:
- Allocates TCS registers ($00-$1F for direct, $20-$FF for stack)
- Tracks register liveness
- Avoids conflicts with user-defined runtime variables
- Handles register spilling to stack if needed

### Example IR

```mlir
// TTL pulse after lowering from qctrl
rtmq.amk "ttl", "1.0", "$01"    // Turn on TTL[0]
rtmq.timer 2500                  // Wait 10us
rtmq.amk "ttl", "1.0", "$00"    // Turn off TTL[0]
```

### Conditional Jump Example

```mlir
// Conditional execution after lowering from qctrl
rtmq.lse $21, $20, 500           // $21 = (adc_value <= 500)
rtmq.amk_ptr $21, ^else_block    // Jump to else if condition true

^then_block:
  rtmq.amk "ttl", "1.0", "$01"
  rtmq.timer 1000
  rtmq.amk "ttl", "1.0", "$00"
  rtmq.amk_ptr "3.0", ^merge_block  // Unconditional jump

^else_block:
  rtmq.amk "ttl", "1.0", "$01"
  rtmq.timer 500
  rtmq.amk "ttl", "1.0", "$00"
  rtmq.amk_ptr "3.0", ^merge_block

^merge_block:
  // Continue
```

## Lowering Passes

### Pass 1: program → catseq

**Location**: `catseq/v2/lowering/program_to_catseq.py`

**Strategy**: Reuse existing `catseq/ast/ast_to_ir.py` converter.

Key transformations:
- `program.execute` → `catseq.atomic`
- `program.sequence` → Chained `catseq.compos`
- `program.for` → Loop unrolling (compile-time constants)
- `program.if` → Forward to qctrl.cond_br (defer to next layer)

### Pass 2: catseq → qctrl

**Location**: `catseq/v2/lowering/catseq_to_qctrl.py`

Key patterns:
- **LowerComposPattern**: Expand composition to time-ordered operations
- **LowerAtomicPattern**: Convert atomic ops to hardware ops (TTLSetOp, RWGLoadOp, etc.)
- **MergeTensorPattern**: Merge parallel operations by board
- **LowerIfPattern**: Convert program.if to qctrl.cond_br with CFG blocks

Critical: This pass computes absolute timestamps for all operations.

### Pass 3: qctrl → rtmq

**Location**: `catseq/v2/lowering/qctrl_to_rtmq.py`

Key patterns:
- **LowerTTLSetPattern**: TTLSetOp → AMKOp with RTMQ mask format
- **LowerWaitPattern**: WaitOp → TimerOp (long) or NOPOp (short)
- **LowerRWGPattern**: RWGLoadOp/PlayOp → Complex AMK sequences
- **LowerCondBrPattern**: CondBrOp → TCS comparison + AMKPTROp

Includes TCS register allocator for runtime variables and temporaries.

## Code Generation

**Location**: `catseq/v2/codegen/rtmq_to_oasm.py`

### RTMQToOASMEmitter

Responsibilities:
1. **Non-recursive IR traversal** (handles deep nesting)
2. **Block-to-code-segment mapping** (for conditional jumps)
3. **Address calculation** (automatic jump target computation)
4. **OASM DSL call generation**

Key advantage over v1 compiler: MLIR's Block/Region structure automatically handles code layout, eliminating the circular dependency between address calculation and cost analysis.

### Example Emission

```python
rtmq.amk "ttl", "1.0", "$01"
  → OASMCall(dsl_func=lambda: amk('ttl', '1.0', '$01'), args=())

rtmq.timer 2500
  → OASMCall(dsl_func=wait_mu, args=(2500,))
```

## Optimization Passes

### Pass A: RWG Pipeline Optimization

**Location**: `catseq/v2/optimization/rwg_pipeline.py`

Identifies RWG load-play pairs and computes optimal scheduling to minimize load deadline violations.

### Pass B: TTL Merge Optimization

**Location**: `catseq/v2/optimization/ttl_merge.py`

Merges consecutive TTL operations on the same board into single bitmask operations.

### Pass C: Dead Code Elimination

**Location**: `catseq/v2/optimization/dead_code.py`

Removes redundant wait operations and identity morphisms.

## Verification Strategy

### Level 1: Dialect Verification
- Type system validation for each operation
- Attribute range checks
- Structural constraints (e.g., channel uniqueness in tensor)

### Level 2: Lowering Verification
- Pre/post-condition checks for each pattern
- Roundtrip testing (where applicable)
- Semantic preservation validation

### Level 3: Code Generation Verification
- OASM code comparison with v1 compiler
- Timing accuracy validation
- Hardware execution testing (simulator + real hardware)

## Testing Strategy

1. **Unit tests**: Each operation and pattern
2. **Integration tests**: End-to-end lowering pipelines
3. **Regression tests**: All 49 existing v1 test cases
4. **New tests**: 20+ tests for Program API features
5. **Stress tests**: Deep nesting, large loops, complex conditionals

## Migration Plan

### Week 9: V2 Compiler Available
- `catseq.v2.compiler_v2.compile_to_oasm_calls_v2()` function ready
- Users can opt-in to v2 compiler for testing

### Week 13: Default to V2
- V2 becomes default compiler
- V1 remains available as fallback
- Migration guide provided

## Performance Targets

- **Compilation time**: ≤ 1.5x v1 compiler (acceptable: 2x)
- **Code quality**: ≥ v1 compiler (acceptable: 5% degradation)
- **Priority**: Correctness > Completeness > Performance

## Risk Mitigation

1. **Isolation**: V2 completely separated in v2/ directory
2. **Fallback**: V1 compiler preserved and functional
3. **Incremental**: Can test both compilers side-by-side
4. **Documentation**: Comprehensive architecture docs

## Development Timeline

- **Week 1 (Phase 0)**: Architecture design & environment setup ✓ IN PROGRESS
- **Week 2-4 (Phase 1)**: Three-layer dialect definitions
- **Week 5-7 (Phase 2)**: Lowering passes implementation
- **Week 8-9 (Phase 3)**: Code generation
- **Week 10-11 (Phase 4)**: Optimization migration
- **Week 12-13 (Phase 5)**: Conditional execution + full testing

## References

- Original design: `.serena/memories/mlir_refactor_design.md`
- Plan document: `~/.claude/plans/shimmying-cuddling-fern.md`
- RTMQ hardware reference: `.serena/memories/rtmq_oasm_reference.md`
- xDSL 0.55 documentation: Via xdsl-055 skill
