---
status: accepted
---

# Use one Serial operator

CatSeq uses `>>` as the only Morphism Serial operator. At every adjacent
boundary, Serial instantiates successor Boundary Binders from the predecessor's
provided record and then requires the complete records to match. The source
operator `@`, the canonical `AutoSerial` and `StrictSerial` distinction, and
per-boundary `BoundaryPolicy` are removed; encountering `@` in the new frontend
produces a migration diagnostic rather than silently aliasing it to `>>`.

The legacy distinction is subsumed by the one rule. Binder instantiation
provides the predecessor-sensitive behavior formerly associated with `>>`, and
complete-record matching provides the incompatibility check formerly associated
with `@`. The new model inserts no implicit state repair or backend adapter, so
a second Serial operator would express no additional semantics.

## Considered options

- Retaining `@` as an alias was rejected because two spellings would imply a
  semantic distinction that no longer exists.
- Retaining `@` as a “no binder” boundary was rejected because it would make
  reusable predecessor-dependent Morphisms unusable without adding safety beyond
  complete-record matching.

## Consequences

ADR 0006 remains authoritative for variadic Serial and Parallel arena shape, but
its per-boundary Auto/Strict policy is superseded. Existing source using `@`
must migrate explicitly to `>>`; a future exact-boundary assertion, if justified
by a concrete use case, requires a separately named construct rather than a
second composition operator.
