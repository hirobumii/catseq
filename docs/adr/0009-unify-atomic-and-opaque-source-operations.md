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

Hardware-event variants carry typed channel effects. Opaque variants instead
carry only board-call definitions, timing, metadata, and provenance. A blackbox
is an explicit escape hatch: CatSeq does not inspect or validate channel state
changes made by its raw OASM callback. This keeps the opaque interface independent
of target state schemas while allowing target lowering to reserve exact board
occupancy and reject overlapping calls.

Exact opaque occupancy uses a half-open interval. A same-board operation or
opaque region may begin exactly at its end boundary, while any positive overlap
remains a compile error.

The sole public spelling `catseq.oasm.black_box` is a compiler special form for
the opaque variant; `catseq.atomic` is not retained as a compatibility module.
Its board calls use stable module-level function identities in native data; live
Python callables remain in the host-side `CompiledSequence` registry and are
resolved by the existing OASM adapter.
Nested closures are not native values, so source passes captured data explicitly
through `user_args` and `user_kwargs`.
The `board_funcs` keys directly define participating boards; there is no
`channel_states` argument. If raw OASM changes hardware state, the user must
preserve it or explicitly re-establish it before later typed operations.
