---
status: accepted
---

# Unify atomic and opaque source operations

Typed Source HIR exposes one sealed `AtomicOp` family. Existing Python
`AtomicMorphism` values lower to its hardware-event variant, while
`TimedRegion` and legacy `BlackBoxAtomicMorphism` values lower to its opaque
region variant. The Rust compiler does not preserve Python inheritance between
these representations and does not accept arbitrary Python callable payloads.

An opaque region carries a `TimingContract`. `Exact(DurationExpr)` permits ordinary
Serial scheduling inside the current Epoch. `Dynamic` makes the Epoch exit time
unknown; no ordinary statically positioned successor may cross that boundary,
and all participating boards must reconverge through a Sync Phi before static
scheduling resumes.

Both variants carry explicit channel state effects, board-call definitions, and
provenance appropriate to their semantics. CatSeq 0.3 does not implement
hardware conditionals; a future implementation would represent them as control
nodes rather than new AtomicOp source types. This keeps the source type family
closed while allowing target lowering and effect analysis to distinguish
instantaneous hardware events, exact opaque occupancy, and runtime-variable
occupancy.
