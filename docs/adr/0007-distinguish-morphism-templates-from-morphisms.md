---
status: accepted
---

# Distinguish Morphism Templates from Morphisms

Typed Source HIR has distinct `MorphismTemplate` and `Morphism` types. The
existing Python API spelling `MorphismDef` resolves to `MorphismTemplate`, so
the public sequencing syntax does not change.

A Morphism Template is a restricted compiler artifact with free channel slots.
It is not an arbitrary Python generator or callable. Binding those slots creates
an `Instantiate` leaf whose value has type `Morphism`; the referenced template
body remains shared in its template segment. Both Morphism Templates and bound
Morphisms express state through an implicit Morphism Effect rather than a
source-visible incoming-state value.

Composing Morphism Templates uses the same variadic Serial and Parallel
structure inside the template definition. It does not add a canonical
composition kind. The type checker rejects uses that require a channel-bound
Morphism where channel slots remain free, or a Morphism Template where a
completed Morphism is required.
