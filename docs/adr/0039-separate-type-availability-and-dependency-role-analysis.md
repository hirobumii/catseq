---
status: accepted
---

# Separate type, availability, and dependency-role analysis

CatSeq analyzes three independent semantic dimensions in separate incremental
queries. `InferTypes(SccId)` unifies base and nominal types across a recursive
definition SCC and publishes stable Type Signatures. `InferAvailability(SccId)`
then solves forward data flow over the `Compile < Link < Device` lattice and
publishes Availability Transfers. `AnalyzeDependencyRoles(SccId)` propagates
resolved use and call edges to publish Structural Dependency Summaries.

Type inference uses type variables and unification, but Value Availability is a
lattice fact rather than part of type equality. Dependency Role is a property of
a use: topology, dispatch, channel selection, and other specialization decisions
are Structural; supported atomic operands and durations are Relocatable. A
single source value may have both kinds of use. Such a value participates in the
Specialization Key and may also produce a relocation; the linker must validate
any structurally captured binding against the artifact specialization.

The three results live in Semantic Fact side tables rather than creating types
such as `RuntimeFloat` or mutable annotations on Source HIR nodes. Type checking
is not repeated for each specialization. A Link value used by a Structural
consumer is rejected, while target-declared Device operands remain legal only
in their declared contexts.

Separating these queries gives each result an independent stable fingerprint.
A scan-binding change can therefore reuse type, availability, role, and
specialization results and invalidate only dependent Value Expressions, RTMQ
fragments, and OASM Call Plans. A semantic change that leaves an earlier query's
normalized result unchanged stops at that query under red-green validation.
