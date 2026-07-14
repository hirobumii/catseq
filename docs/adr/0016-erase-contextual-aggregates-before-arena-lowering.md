---
status: accepted
---

# Erase contextual aggregates before Morphism arena lowering

The canonical Morphism arena directly represents the sequencing DAG. It has no
container node kinds and stores no Python `list`, `tuple`, or `dict` values.
Variadic Serial and Parallel children are ranges in the arena's shared edge
table, not source-language containers.

Typed Source HIR may temporarily represent contextual aggregates needed to
understand existing source spelling. Examples include a Compile-time
`Optional[T]`, channel bindings spelled as `dict[Channel, MorphismDef]`, and
fixed aggregate arguments accepted by an Atomic Operation schema. These values
are frontend semantics rather than Morphism structure.

Specialization and typed lowering must eliminate every contextual aggregate:

- a channel-binding value becomes channel-bound `Instantiate` leaves under a
  Parallel node when it is consumed by composition;
- a Compile-time optional discriminant selects one specialized path;
- an Atomic Operation argument aggregate becomes a typed operation payload or
  target relocation described by that operation's schema.

Failure to eliminate such a value is a lowering error. CatSeq 0.3 does not add
general mutable containers, dynamic container indexing, or container nodes to
the Morphism arena. The same boundary applies to every other Python-shaped
operation: attribute lookup, dataclass replacement, and source expressions are
resolved or lowered to native handles and Value Expression IDs before arena
construction.
