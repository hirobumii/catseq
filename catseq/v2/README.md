# CatSeq V2 - MLIR/xDSL Compiler

**Status**: 🚧 Under Active Development (Phase 0)

**Start Date**: 2026-01-18
**Target Completion**: 2026-04-18 (13 weeks)
**Branch**: `feature/ast-mlir-refactor`

## Overview

V2 is a complete rewrite of the CatSeq compiler using MLIR/xDSL architecture with three-layer dialects. This enables:

✅ Native support for runtime conditional execution
✅ Better modularity and extensibility
✅ Powerful optimization framework
✅ Clear IR hierarchy for debugging

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for complete design documentation.

```
Program AST → program dialect → catseq dialect → qctrl dialect → rtmq dialect → OASM
```

## Development Status

### Phase 0: Preparation (Week 1) - ✅ COMPLETED

- [x] Create v2/ directory structure
- [x] Write architecture documentation
- [x] Verify xDSL 0.55.0 environment
- [x] Design detailed type system for catseq dialect
- [x] Set up testing framework for dialects
- [x] Create development workflow documentation

### Phase 1: Three-Layer Dialect Definition (Week 2-4) - 🔄 IN PROGRESS

#### Week 2: catseq Dialect - ✅ COMPLETED
- [x] Define ChannelType, StateType, MorphismType
- [x] Implement ComposOp, TensorOp, IdentityOp, AtomicOp
- [x] Write verification rules
- [x] Unit tests for all operations (20/20 passing)

#### Week 3: qctrl Dialect
- [ ] Define TTLSetOp, WaitOp, RWGLoadOp, RWGPlayOp
- [ ] **CRITICAL**: Implement CondBrOp for runtime conditionals
- [ ] Define SequenceOp container with regions
- [ ] Unit tests + IR roundtrip tests

#### Week 4: rtmq Dialect
- [ ] Define AMKOp, SFSOp, TimerOp, NOPOp
- [ ] Implement TCS comparison ops: LSEOp, EQUOp, NEQOp
- [ ] Implement AMKPTROp for conditional/unconditional jumps
- [ ] Design TCS register allocator
- [ ] Unit tests + verification

### Phase 2: Lowering Passes (Week 5-7) - ⏳ PENDING

#### Week 5: program → catseq
- [ ] Reuse existing AST → program dialect converter
- [ ] Implement program → catseq lowering patterns
- [ ] Handle Morphism registry migration
- [ ] End-to-end tests

#### Week 6: catseq → qctrl (CRITICAL WEEK)
- [ ] LowerComposPattern - expand compositions
- [ ] LowerAtomicPattern - convert to hardware ops
- [ ] **CRITICAL**: LowerIfPattern - program.if → qctrl.cond_br
- [ ] Timestamp calculation logic
- [ ] Epoch boundary detection

#### Week 7: qctrl → rtmq
- [ ] LowerTTLSetPattern - TTL → AMK
- [ ] LowerWaitPattern - Wait → Timer/NOP
- [ ] LowerRWGPattern - RWG → AMK sequences
- [ ] **CRITICAL**: LowerCondBrPattern - CondBr → TCS jumps
- [ ] Implement TCS register allocator

### Phase 3: Code Generation (Week 8-9) - ⏳ PENDING

#### Week 8: rtmq → OASM Emitter
- [ ] Non-recursive IR traversal
- [ ] Block-to-code-segment mapping
- [ ] Automatic jump address calculation
- [ ] OASM DSL call generation

#### Week 9: Integration & Testing
- [ ] Create `compiler_v2.py` entry point
- [ ] Provide v1/v2 switching mechanism
- [ ] Compare v1/v2 generated code
- [ ] Performance benchmarking

### Phase 4: Optimization Migration (Week 10-11) - ⏳ PENDING

#### Week 10: RWG Pipeline
- [ ] Port RWG load-play scheduling from v1
- [ ] Implement as qctrl-level optimization pass
- [ ] Verify deadline constraints

#### Week 11: Other Optimizations
- [ ] TTL merge optimization
- [ ] Dead code elimination
- [ ] Hardware loop generation (RTMQ for_ instruction)

### Phase 5: Conditional Support + Testing (Week 12-13) - ⏳ PENDING

#### Week 12: Conditional Execution
- [ ] End-to-end tests: simple if-then
- [ ] Tests: if-then-else
- [ ] Tests: nested conditionals
- [ ] Tests: conditional + loop combinations

#### Week 13: Final Testing & Release
- [ ] All 49 v1 regression tests passing
- [ ] 20+ new Program API tests
- [ ] Performance validation (≤ 1.5x v1)
- [ ] Documentation updates
- [ ] Migration guide

## Environment

- **Python**: 3.12+
- **xDSL**: 0.55.0 ✅
- **OASM**: (existing dependency)
- **Branch**: feature/ast-mlir-refactor

## Usage (Post-Week 9)

```python
from catseq.v2.compiler_v2 import compile_to_oasm_calls_v2

# Use V2 compiler
oasm_calls = compile_to_oasm_calls_v2(program_or_morphism)

# Or use V1 compiler (fallback)
from catseq.compilation.compiler import compile_to_oasm_calls
oasm_calls = compile_to_oasm_calls(morphism)
```

## Testing

```bash
# Run V2 dialect tests
pytest catseq/v2/dialects/tests/

# Run V2 lowering tests
pytest catseq/v2/lowering/tests/

# Run all V2 tests
pytest catseq/v2/
```

## Documentation

- [ARCHITECTURE.md](./ARCHITECTURE.md) - Complete architecture design
- [../dialects/program_dialect.py](../dialects/program_dialect.py) - Existing program dialect (reused)
- [../ast/ast_to_ir.py](../ast/ast_to_ir.py) - Existing AST converter (reused)

## Contributing

During development (13 weeks), all work is in `catseq/v2/`. The v1 compiler in `catseq/compilation/` remains untouched as a fallback.

## Key Design Decisions

1. **Closed Development**: 13 weeks, one-time delivery
2. **Reuse Existing Code**: Program API and AST converter
3. **Complete Isolation**: New code in v2/, old code preserved
4. **Fallback Strategy**: V1 always available for rollback
5. **Priority**: Correctness > Completeness > Performance

## References

- Plan: `~/.claude/plans/shimmying-cuddling-fern.md`
- Original design: `.serena/memories/mlir_refactor_design.md`
- RTMQ reference: `.serena/memories/rtmq_oasm_reference.md`
