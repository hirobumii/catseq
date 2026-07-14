---
status: accepted
---

# Use variadic Serial and Parallel composition nodes

The canonical Rust arena has two composition kinds: variadic Serial and
variadic Parallel. Atomic operations, template instantiations, waits, repeats,
references, and other non-composition operations remain leaf or control nodes.

Serial stores an ordered child list and one boundary policy between every pair
of adjacent children. A boundary policy preserves the existing `>>` automatic
state inference or `@` strict state matching semantics. Parallel stores an
ordered child list and applies Parallel Alignment across all children at once.

The arena stores child references in a flat edge table addressed by a range
from the node rather than allocating a Python object or independent vector for
each composition. Source lowering flattens associative runs without inlining
through template instantiation or definition boundaries.

`Morphism >> dict[Channel, MorphismDef]` is frontend syntax. Typed HIR lowers
the dictionary to a Parallel group of channel-bound template instantiations and
then includes that group as the next Serial child. The canonical arena has no
ApplyMap or DeferredApply composition kind.

This representation reduces composition depth and treats dictionary
application, ordinary parallel composition, and service-template composition
uniformly. Per-child and per-boundary provenance is retained so flattening does
not weaken diagnostics.
