# CatSeq Dialect Type System Design

## Overview

This document defines the type system for the catseq dialect, which represents high-level Morphism abstractions based on Monoidal Category Theory.

## Design Principles

1. **Board/Channel Addressing**: Use (board_type, board_id, local_id, channel_type) tuple for complete channel identification
2. **String-based Types**: Use string attributes for board_type and channel_type for MLIR readability
3. **Extensibility**: Easy to add new board types and channel types
4. **Type Safety**: xDSL's type system ensures compile-time validation

## Type Definitions

### 1. ChannelType

Represents a physical channel on a specific board.

**xDSL Definition:**
```python
from xdsl.ir import ParametrizedAttribute
from xdsl.irdl import irdl_attr_definition, param_def
from xdsl.dialects.builtin import IntegerAttr, StringAttr

@irdl_attr_definition
class ChannelType(ParametrizedAttribute):
    name = "catseq.channel"
    
    board_type = param_def(StringAttr)    # "rwg", "main", "rsp"
    board_id = param_def(IntegerAttr)     # 0, 1, 2, ...
    local_id = param_def(IntegerAttr)     # Channel index on board (0-based)
    channel_type = param_def(StringAttr)  # "ttl", "rwg", "rsp"
```

**MLIR Syntax Examples:**
```mlir
!catseq.channel<"rwg", 0, 0, "ttl">     // RWG_0, TTL channel 0
!catseq.channel<"rwg", 0, 1, "ttl">     // RWG_0, TTL channel 1
!catseq.channel<"rwg", 1, 0, "rwg">     // RWG_1, RWG channel 0
!catseq.channel<"main", 0, 5, "ttl">    // MAIN board, TTL channel 5
!catseq.channel<"rsp", 0, 0, "rsp">     // RSP_0, RSP channel 0
```

**Board Type Values:**
- `"rwg"` - Radio Wave Generator boards (RWG_0, RWG_1, ...)
- `"main"` - Main control board
- `"rsp"` - Real-time Signal Processor boards

**Channel Type Values:**
- `"ttl"` - TTL (Transistor-Transistor Logic) channel
- `"rwg"` - RWG waveform generation channel
- `"rsp"` - RSP signal processing channel

**Mapping to Current System:**
```python
# Old: "RWG_0_TTL_0"
# New: !catseq.channel<"rwg", 0, 0, "ttl">

# Old: "RWG_1_RWG_2"
# New: !catseq.channel<"rwg", 1, 2, "rwg">
```

### 2. StateType

Represents the state of a channel at a specific time.

**xDSL Definition:**
```python
@irdl_attr_definition
class StateType(ParametrizedAttribute):
    name = "catseq.state"
    
    channel = param_def(ChannelType)      # Which channel
    state_data = param_def(DictionaryAttr) # State-specific data (e.g., {value: 0/1} for TTL)
```

**MLIR Syntax Examples:**
```mlir
// TTL OFF state
!catseq.state<
  !catseq.channel<"rwg", 0, 0, "ttl">,
  {value = 0 : i32}
>

// TTL ON state
!catseq.state<
  !catseq.channel<"rwg", 0, 0, "ttl">,
  {value = 1 : i32}
>

// RWG waveform state
!catseq.state<
  !catseq.channel<"rwg", 0, 0, "rwg">,
  {
    frequency = 100.0 : f64,
    amplitude = 0.5 : f64,
    phase = 0.0 : f64
  }
>
```

**State Data Schema:**

For **TTL channels**:
- `value: i32` - 0 (OFF) or 1 (ON)

For **RWG channels**:
- `frequency: f64` - Frequency in Hz
- `amplitude: f64` - Amplitude (normalized 0.0-1.0)
- `phase: f64` - Phase in radians

For **RSP channels**:
- `threshold: f64` - Detection threshold
- `gain: f64` - Amplification gain

### 3. MorphismType

Represents a state transformation (morphism) in the Category Theory sense.

**xDSL Definition:**
```python
@irdl_attr_definition
class MorphismType(ParametrizedAttribute):
    name = "catseq.morphism"
    
    domain = param_def(StateType)         # Input state
    codomain = param_def(StateType)       # Output state
    duration = param_def(IntegerAttr)     # Duration in clock cycles (250 MHz)
```

**MLIR Syntax Examples:**
```mlir
// TTL pulse morphism: OFF → ON, 1 cycle (4ns)
!catseq.morphism<
  !catseq.state<!catseq.channel<"rwg", 0, 0, "ttl">, {value = 0}>,
  !catseq.state<!catseq.channel<"rwg", 0, 0, "ttl">, {value = 1}>,
  1
>

// Wait morphism: ON → ON, 2500 cycles (10μs)
!catseq.morphism<
  !catseq.state<!catseq.channel<"rwg", 0, 0, "ttl">, {value = 1}>,
  !catseq.state<!catseq.channel<"rwg", 0, 0, "ttl">, {value = 1}>,
  2500
>

// Complex morphism: OFF → ON with waveform load
!catseq.morphism<
  !catseq.state<!catseq.channel<"rwg", 0, 0, "rwg">, {frequency = 0.0, amplitude = 0.0}>,
  !catseq.state<!catseq.channel<"rwg", 0, 0, "rwg">, {frequency = 100.0, amplitude = 0.5}>,
  100
>
```

## Type Constraints

### Channel Uniqueness (for Tensor Product)

When performing tensor product (parallel composition) `|`, channels must be disjoint:

```python
from xdsl.irdl import irdl_op_definition, IRDLOperation, operand_def

@irdl_op_definition
class TensorOp(IRDLOperation):
    name = "catseq.tensor"
    
    lhs = operand_def(MorphismType)
    rhs = operand_def(MorphismType)
    result = result_def(MorphismType)
    
    def verify_(self) -> None:
        # Extract channels from lhs and rhs
        lhs_channel = self.lhs.type.domain.channel
        rhs_channel = self.rhs.type.domain.channel
        
        # Ensure channels are different
        if lhs_channel == rhs_channel:
            raise VerifyException(
                f"Tensor product requires disjoint channels, "
                f"but both operands use {lhs_channel}"
            )
```

### State Continuity (for Composition)

When performing composition `@`, the codomain of the first morphism must match the domain of the second:

```python
@irdl_op_definition
class ComposOp(IRDLOperation):
    name = "catseq.compos"
    
    lhs = operand_def(MorphismType)
    rhs = operand_def(MorphismType)
    result = result_def(MorphismType)
    
    def verify_(self) -> None:
        # Extract states
        lhs_end = self.lhs.type.codomain
        rhs_start = self.rhs.type.domain
        
        # Ensure state continuity
        if lhs_end != rhs_start:
            raise VerifyException(
                f"Composition requires state continuity: "
                f"lhs.codomain = {lhs_end}, rhs.domain = {rhs_start}"
            )
```

## Time Representation

**Base Unit**: Clock cycles (250 MHz = 4ns per cycle)

**Conversion:**
- 1 μs = 250 cycles
- 1 ms = 250,000 cycles
- User specifies time in microseconds, internally converted to cycles

**Example:**
```python
# User code
wait(40e-6)  # 40 microseconds

# Internal representation
# duration = 40e-6 * 250e6 = 10,000 cycles
!catseq.morphism<..., 10000>
```

## Extensibility

### Adding New Board Types

Simply add new string values:
```python
# Current: "rwg", "main", "rsp"
# Future: "awg", "daq", "counter", etc.
!catseq.channel<"awg", 0, 0, "analog">
!catseq.channel<"daq", 1, 3, "adc">
```

### Adding New Channel Types

Add new string values and define state schemas:
```python
# New channel type: "analog"
!catseq.channel<"awg", 0, 0, "analog">

# New state data schema
!catseq.state<
  !catseq.channel<"awg", 0, 0, "analog">,
  {voltage = 2.5 : f64, offset = 0.0 : f64}
>
```

## Integration with Existing Code

### From Current Morphism System

```python
# Current Python code
from catseq.morphism import Channel, Board

ch = Channel(Board("RWG_0"), 0, "ttl")

# Maps to catseq dialect type
!catseq.channel<"rwg", 0, 0, "ttl">
```

### From Program AST

The existing `catseq/ast/ast_to_ir.py` converter will:
1. Convert `Morphism` objects to `catseq.atomic` operations
2. Encode channel information in ChannelType
3. Encode state transitions in MorphismType

## Verification Strategy

### Type-Level Verification
- xDSL's type system ensures all operands have correct types
- ChannelType, StateType, MorphismType constraints enforced at IR construction

### Operation-Level Verification
- ComposOp checks state continuity
- TensorOp checks channel disjointness
- Custom verify_() methods for each operation

### Lowering-Level Verification
- Pre/post-conditions for each lowering pattern
- Ensure semantic preservation during transformations

## Next Steps

1. Implement these type definitions in `catseq/v2/dialects/catseq_dialect.py`
2. Write unit tests for type construction and constraints
3. Implement core operations (ComposOp, TensorOp, IdentityOp, AtomicOp)
4. Verify roundtrip: construct → print → parse → construct
