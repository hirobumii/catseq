---
status: accepted
---

# Close the 0.3 source type universe

CatSeq 0.3 source values belong to a closed compiler-owned universe. Scalars
are Unit, Bool, Int64, Float64, Duration, and Compile-only String. Native handles
are Board, nominal `Channel<ChannelKindId>`, immutable
`Instance<CompileClassSchema>`, and typed `ScanParam<T>`. Sequencing values are
Morphism, MorphismTemplate, and the sealed AtomicOp family.

Typed Source HIR additionally permits contextual Optional values, fixed tuples,
registered native records, channel bindings, and scan bindings. They are not
general Python containers or objects and must be consumed or flattened before
canonical arena publication. Functions, classes, and modules are not first-
class runtime values.

Int64 may promote implicitly to Float64. Bool does not promote to Int64, and
neither Int64 nor Float64 converts implicitly to Duration. Duration construction
and Cycle Quantization remain explicit. `T | None` is supported only as a
Compile-discriminated Optional rather than as a general union.

Hardware extension occurs through registered Record Schemas, Channel Kind IDs,
and internal State Type IDs, not arbitrary Python classes. State Environments,
State Types, Morphism Effects, and Phase Frame IDs are compiler semantics rather
than source-language values. A native Loop induction variable is `Int64 @
Device` and may be consumed only by target-declared loop-register operands.
