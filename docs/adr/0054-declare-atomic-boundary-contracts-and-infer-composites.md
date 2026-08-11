---
status: accepted
---

# Declare atomic Boundary Contracts and infer composite contracts

The versioned Atomic Schema is the authority for each primitive Atomic
Operation's Boundary Contract. The compiler derives the minimal contract of a
Morphism Definition compositionally from its body, including explicit value
derivations and resource-indexed fact edges; source authors do not duplicate
that contract in a second manually maintained signature.

For every Resource Slot used by an Atomic Operation, its Atomic Schema declares
the complete minimal input and output boundary records. Facts preserved across
the operation are carried explicitly through symbolic variables; omission never
means that a fact on a used resource remains unchanged. Only Resource Slots
outside the Morphism's Resource Support frame through automatically.

Each Channel Kind owns one canonical versioned Boundary Schema that defines
what a complete compiler-relevant record contains. Atomic Schemas reference
that shared type, Morphism Definitions infer compositions over it, and target
backends only consume resolved records. A backend cannot extend the schema with
an undeclared compiler-relevant field; genuinely different boundary semantics
require a schema version change or a distinct Channel Kind.

An Atomic Schema input pattern may introduce Boundary Binders for fields that
its output record or value derivations reuse. Serial composition binds them to
the predecessor's concrete or symbolic Value Expression IDs and substitutes
those IDs into the successor outputs. Binders are schema-internal names, not
source variables or runtime parameters.

An Atomic Schema may contain a finite set of Boundary Transition Clauses when
one operation accepts several Boundary Schema variants. Their complete input
patterns must be mutually exclusive. Together the clauses define one
deterministic, piecewise partial Boundary Transformer. A context-open Morphism
preserves that transformer without choosing a case, and Serial composition is
partial-function composition. Once a concrete predecessor record reaches an
Atomic Operation, at most one clause matches; no candidate-clause Control node
or runtime Branch exists. Existing RWG `load` behavior requires this form
because it accepts `Ready`, `Active`, and `ActiveUnknown` inputs while rejecting
pending-transition variants.

Boundary sufficiency is a required semantic law. For any two prefixes `P1` and
`P2`, if their projected Boundary records are equal,

```text
B(P1) = B(P2)
```

then elaborating the same suffix `M` must produce equal suffix semantics:

```text
project_M(elaborate(P1 >> M)) = project_M(elaborate(P2 >> M))
```

This equality covers emitted semantic operations and operands, timing and
completion, resource claims and hazards, produced values and readiness,
operation legality, and mandatory failure behavior. Arbitrary earlier history
cannot change the suffix once these records agree.

A fact is mandatory in a Boundary Schema exactly when changing it can change at
least one of those observable properties. Facts that cannot affect any of them
may remain optional State Refinement; they cannot be consulted later as an
undeclared lowering input.

Target lowering consumes a context-closed Morphism whose required operands and
boundary facts have already been resolved. It may check target capabilities, but
it must not discover operation legality, payload dependencies, timing, resource
effects, produced values, or mandatory failures by consulting an ambient mutable
hardware-state map. If source contract annotations are introduced later, they
are checked assertions about the inferred contract rather than an independent
semantic authority.

A reusable Morphism Definition or Kernel Function may infer a non-empty
`Requires` set. Those requirements propagate through callers. The Selected
Compile Entry, however, must have an empty external `Requires` set after
composition. The Compile Environment cannot discharge mutable Boundary
requirements, and the first version has no session-supplied root Boundary
record. Root facts must instead be established by explicit zero-requirement
Morphism operations such as hardware initialization. Thus a context-open
`linear_ramp` helper is legal, while selecting a root that calls it without an
explicit predecessor is a compile-time error.

This supersedes ADR 0010's model of every Morphism as a transformation over an
implicitly threaded State Environment. Its useful source-language constraint is
retained: source code does not pass `StateMap` values or call `get_end_state` to
connect sequencing services. Those dependencies are instead explicit Boundary
Contract and value edges, while unrelated hardware knowledge may remain an
optional State Refinement.

## Considered options

- Manually declaring contracts on every Morphism Definition was rejected because
  the declaration can drift from the body and makes composition less automatic.
- Recovering contracts during target lowering was rejected because it gives the
  backend hidden semantic authority and makes history closure untestable before
  lowering.
- Sparse updates with default preservation were rejected because an omitted
  compiler-relevant change would silently retain a false fact. Complete local
  records make preservation and invalidation explicit in the authoritative
  Atomic Schema.
- Operation-specific or backend-specific boundary record types were rejected
  because “complete” would have no common meaning and Serial composition would
  require implicit adapters or hidden field recovery.
- Optional-field union records and ordered fallback clauses were rejected for
  multi-input operations because they admit impossible field combinations or
  make semantics depend on clause order.
- Treating unresolved clause cases as competing candidates was rejected because
  mutually exclusive clauses already denote one deterministic partial function.
  Context-open composition preserves and composes that function; it does not
  introduce another choice abstraction.
- Session-supplied root Boundary records were rejected for the first version
  because they would make standalone artifacts depend on mutable executor state
  and reintroduce a root State Environment contract. Stateful continuation
  kernels require a separate runtime protocol if they are added later.

## Consequences

`linear_ramp` must expose its incoming active snapshot and its derived ramp,
endpoint, and outgoing snapshot values in the canonical value/effect graph.
Existing mutable RWG state tracking may remain during migration, but it cannot
be the only source of any compiler-relevant fact.

Only a Selected Compile Entry is required to be context-closed. Reusable helper
definitions remain composable precisely because their inferred requirements may
stay open until a caller supplies them.

Parallel exclusivity remains a law of the Morphism algebra: branch Resource
Supports must be disjoint before their Boundary Contracts are merged. Boundary
Contracts do not introduce a second linear-capability system or duplicate the
resource-support validation owned by issue #38.
