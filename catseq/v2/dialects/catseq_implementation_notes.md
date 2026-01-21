# CatSeq Dialect Implementation Notes

## Version: 0.3.0-dev (Simplified Architecture)

**Last Updated**: 2026-01-20

## Executive Summary

The catseq dialect implements a **simplified, channel-focused** abstraction layer for quantum control operations. Based on Category Theory, it provides a tree-structured IR for composing control sequences while deferring state management to lower layers.

**Key Design Decision**: catseq handles **ONLY channels + duration**, not states.

## Architecture Overview

### Type System

**ChannelType** - Physical hardware channel identification
```
!catseq.channel<board_type, board_id, local_id, channel_type>

Examples:
  !catseq.channel<"rwg", 0, 0, "ttl">    // RWG_0, TTL channel 0
  !catseq.channel<"rwg", 1, 2, "rwg">    // RWG_1, RWG channel 2
```

**MorphismType** - Single-channel time-bounded transformation
```
!catseq.morphism<channel, duration>

Examples:
  !catseq.morphism<!catseq.channel<"rwg", 0, 0, "ttl">, 100>   // 100 cycles on ch0
  !catseq.morphism<!catseq.channel<"rwg", 0, 1, "ttl">, 2500>  // 2500 cycles on ch1
```

**CompositeMorphismType** - Multi-channel morphism (result of tensor product)
```
!catseq.composite<[morphism1, morphism2, ...]>

Properties:
  - get_channels() -> set[ChannelType]
  - get_duration() -> int  (max of component durations)
```

### Operations

**AtomicOp** - Leaf node operations
```python
%result = catseq.atomic<"op_name"> {
    channel = !catseq.channel<...>,
    duration = N,
    params = <any Attribute>  # Strong-typed!
}

Operations:
  - "ttl_init", "ttl_on", "ttl_off"
  - "rwg_load", "rwg_play"
  - "rsp_measure", "rsp_threshold"
```

**IdentityOp** - Wait/hold operations
```python
%result = catseq.identity {
    channel = !catseq.channel<...>,
    duration = N
}
```

**ComposOp** - Serial composition (@)
```python
%result = catseq.compos %lhs, %rhs

Supports:
  - MorphismType @ MorphismType → MorphismType
  - CompositeMorphismType @ CompositeMorphismType → CompositeMorphismType

Verification:
  - Same channel (simple)
  - Same channel set (composite)
  - Duration = lhs.duration + rhs.duration
```

**TensorOp** - Parallel composition (|)
```python
%result = catseq.tensor %lhs, %rhs

Supports:
  - MorphismType | MorphismType → CompositeMorphismType
  - MorphismType | CompositeMorphismType → CompositeMorphismType
  - CompositeMorphismType | MorphismType → CompositeMorphismType
  - CompositeMorphismType | CompositeMorphismType → CompositeMorphismType

Verification:
  - All channels must be disjoint
  - Duration = max(all morphism durations)
```

## Tree-Structured IR

catseq uses a **tree structure (AST)** where:

**Leaf Nodes**:
- `AtomicOp` - Primitive operations
- `IdentityOp` - Wait operations

**Internal Nodes**:
- `ComposOp` (@) - Serial composition (binary)
- `TensorOp` (|) - Parallel composition (binary)

**Example Tree**:
```
Expression: ((A @ B) | (C @ D)) @ ((E @ F) | (G @ H))

Tree Structure:
             ComposOp
            /         \
        TensorOp    TensorOp
       /      \     /      \
  ComposOp ComposOp ComposOp ComposOp
  /   \    /   \   /   \    /   \
 A     B  C     D E     F  G     H
```

This tree structure enables:
- Recursive composition without limits
- Efficient traversal and transformation
- Clear semantic boundaries

## Performance Characteristics

**Validated with stress tests (10000+ layers)**:

| Test Case | Layers/Channels | Build Time | Status |
|-----------|-----------------|------------|--------|
| Serial Composition | 10,000 layers | 0.93s | ✅ PASS |
| Recursive Parallel | 10,000 layers (10,001 ch) | 6.43s | ✅ PASS |
| Mixed Composition | 1,000 layers | 1.69s | ✅ PASS |
| Wide Parallel | 10,000 channels | 4.36s | ✅ PASS |
| Verification (1000-layer) | 100 iterations | 0.02ms avg | ✅ PASS |

**Key Insights**:
- ✅ No stack overflow for deep nesting
- ✅ Linear time complexity for serial composition
- ✅ Sub-linear verification time
- ✅ Handles 10,000+ channels efficiently

## Design Rationale

### Why Remove State Tracking?

**Problem**: State-based morphisms `(domain, codomain, duration)` were too rigid:
- Required exact state matching at compile time
- Prevented flexible composition patterns
- Made type inference complex

**Solution**: Channel-only morphisms `(channel, duration)`:
- Simpler type system
- More flexible composition
- State inference deferred to qctrl lowering pass

**Trade-off**: State continuity errors caught later (at lowering) instead of at IR construction.

### Why Support Recursive Composition?

**Critical Capability**: Complex control sequences require deep nesting:

```python
# Example: Ramsey sequence with 1000 repetitions
init = ttl_init(ch)
π2_pulse = ttl_on(ch) @ wait(π2_time) @ ttl_off(ch)
free_evolution = wait(ramsey_time)
detection = ttl_on(ch) @ wait(detect_time) @ ttl_off(ch)

# Single iteration
iteration = π2_pulse @ free_evolution @ π2_pulse @ detection

# 1000 iterations (deep nesting!)
full_sequence = init
for _ in range(1000):
    full_sequence = full_sequence @ iteration
```

Without recursive composition, this pattern is impossible.

### Why Strong-Typed Params?

**Problem**: `DictionaryAttr` for params was weakly typed:
```python
# Old (weak typing)
params = {"waveform": ..., "amplitude": ...}  # Runtime errors!
```

**Solution**: Use `Attribute` base class for strong typing:
```python
# New (strong typing)
params = StaticWaveformAttr(samples=[...], duration=...)  # Compile-time safety!
```

**Benefits**:
- Type errors caught at compile time
- Better IDE support
- Safer lowering passes

## Lowering Strategy

### catseq → qctrl Lowering

The qctrl dialect will reconstruct states from atomic operation names:

```python
# catseq IR (channel-only):
%0 = catseq.atomic<"ttl_on"> {channel=ch0, duration=1}
%1 = catseq.identity {channel=ch0, duration=2500}
%2 = catseq.atomic<"ttl_off"> {channel=ch0, duration=1}
%3 = catseq.compos %0, %1
%4 = catseq.compos %3, %2

# Lowered to qctrl (with states):
%s0 = qctrl.ttl_state<OFF>
%s1 = qctrl.ttl_state<ON>
%op0 = qctrl.ttl_set %ch0, %s1 : OFF -> ON, 1 cycle
%op1 = qctrl.wait %ch0 : ON -> ON, 2500 cycles
%op2 = qctrl.ttl_set %ch0, %s0 : ON -> OFF, 1 cycle
```

**State Inference Rules**:
1. `ttl_init` → sets to OFF
2. `ttl_on` → OFF → ON transition
3. `ttl_off` → ON → OFF transition
4. `identity/wait` → preserves current state

**Verification at Lowering**:
- Check state continuity: `lhs.end_state == rhs.start_state`
- Report errors with helpful suggestions
- Insert implicit state transitions if needed

## Migration from Old Design

### Breaking Changes

**Removed**:
- `StateType` - No longer exists
- `MorphismType(domain, codomain, duration)` - Simplified to `(channel, duration)`

**Changed**:
- `AtomicOp.params` - Now `Attribute` instead of `DictionaryAttr`
- `ComposOp` - Now accepts `CompositeMorphismType`
- `TensorOp` - Now accepts `CompositeMorphismType` and returns `CompositeMorphismType`

**Added**:
- `CompositeMorphismType` - Represents multi-channel morphisms

### Migration Guide

**Old Code**:
```python
# Define states
off_state = StateType(channel, {"value": 0})
on_state = StateType(channel, {"value": 1})

# Create morphism
ttl_on = AtomicOp(
    op_name="ttl_on",
    channel=channel,
    domain=off_state,
    codomain=on_state,
    duration=1,
)
```

**New Code**:
```python
# No need for states!
ttl_on = AtomicOp(
    op_name="ttl_on",
    channel=channel,
    duration=1,
)
```

## Future Work

### Phase 2: Auto-Inference Composition (>>)

Add `AutoComposOp` for relaxed composition:

```python
# Strict @ requires exact channel match
f: ch0 @ g: ch0  ✅
f: ch0 @ g: ch1  ❌

# Relaxed >> auto-pads missing channels
f: ch0 >> g: ch1  →  (f | id_ch1) @ (id_ch0 | g)  ✅
```

### Phase 3: Execute Boundary Verification

Add compile-time warnings at `program.execute()` boundary:
- Uninitialized channel usage
- Potential resource leaks
- Duration mismatches in parallel blocks

### Phase 4: Optimization Passes

- Dead code elimination (unused channels)
- Duration alignment optimization
- TTL merge (combine adjacent set operations)

## Testing Strategy

**Unit Tests** (`test_catseq_dialect.py`):
- Type construction and properties
- Basic composition operations
- Verification rules

**Stress Tests** (`test_catseq_dialect_stress.py`):
- 10,000+ layer deep nesting
- 10,000+ channel wide parallel
- Performance benchmarks
- Edge cases (zero duration, single operation)

**Integration Tests** (future):
- catseq → qctrl lowering
- State inference correctness
- Error reporting quality

## References

- **Monoidal Category Theory**: Mac Lane, "Categories for the Working Mathematician"
- **MLIR Design**: https://mlir.llvm.org/docs/
- **xDSL Framework**: https://github.com/xdslproject/xdsl
- **catseq_algebraic_design.md**: Mathematical foundation (note: implementation differs)

## Appendix: xDSL Integration

### Custom Attribute Registration

```python
@irdl_attr_definition
class ChannelType(ParametrizedAttribute):
    name = "catseq.channel"
    # ... parameters ...
```

### Operation Definition Pattern

```python
@irdl_op_definition
class ComposOp(IRDLOperation):
    name = "catseq.compos"
    lhs = operand_def(MorphismType | CompositeMorphismType)
    rhs = operand_def(MorphismType | CompositeMorphismType)
    result = result_def(MorphismType | CompositeMorphismType)

    def verify_(self) -> None:
        # Custom verification logic
        pass
```

### Type Union Support (Python 3.12)

```python
# Native union types instead of Union[...]
lhs = operand_def(MorphismType | CompositeMorphismType)
```

This is a Python 3.12 feature that makes the code cleaner and more readable.
