---
status: accepted
---

# Evaluate Typed HIR directly into native arenas

After name, type, Availability, and Dependency Role facts are complete, a Rust
abstract evaluator specializes Typed Source HIR directly into the native Value
Expression and Morphism arenas. Its closed value family contains native
scalars, Value Expression IDs, Compile Instances, template handles, Morphism
roots, and temporary Contextual Aggregates; it never constructs Python objects.

Compile-known control and pure data operations are evaluated, scalar Link
operations emit Value Expressions, intrinsics emit native values or Atomic
Operations, composition emits canonical Morphism nodes, and resolved source
calls request cached definition specializations. Python records, call objects,
and containers are normalized during this traversal. Sequencing loops are the
exception to compile-time control evaluation and are preserved as native loop
regions.

There is no persistent normalized-HIR copy between Typed Source HIR and the two
native arenas. The final Morphism arena has no `SourceCall`, `DeferredApply`,
Python payload, or Source HIR owner. Evaluation and specialization use explicit
native frame stacks rather than recursive Rust calls.
