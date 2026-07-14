---
status: accepted
---

# Use a schema and template intrinsic registry

Intrinsic Modules are backed by a versioned Rust registry rather than by
parsing or executing their Python implementations. The registry has three
closed lowering forms: declarative Atomic Schemas, precompiled native Morphism
Templates, and a small set of compiler Special Forms.

An Atomic Schema declares its stable symbol and ID, type signature, Channel
Kind, parameter roles and constraints, Availability and Dependency Role rules,
Morphism Effect, Timing Contract, target lowering operation, and semantic
version. Ordinary composite hardware APIs such as pulse and ramp builders are
precompiled from these primitives into the same native template arena used by
source definitions; invocation creates an Instantiate node instead of running a
Rust callback or Python generator.

Only operations that alter language semantics, including supported dataclass
replacement, identity construction, loop formation, template binding, and
declared unit conversion, are Rust Special Forms. Pure constants and scalar
operations lower to native compile values or Value Expressions. Registry
semantic digests participate in the Query DAG so changing an intrinsic
invalidates only its actual consumers.
