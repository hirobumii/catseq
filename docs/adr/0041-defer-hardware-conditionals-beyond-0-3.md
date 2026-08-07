---
status: accepted
---

# Defer hardware conditionals beyond 0.3

CatSeq 0.3 supports an ordinary source `if` only when its predicate has Compile
Value Availability. Specialization evaluates the predicate, records its
Structural dependencies, and lowers only the selected arm. A predicate with
Link or Device availability is a compile error.

Consequently 0.3 introduces no Branch Region, canonical Branch node, or RTMQ
branch fragment. Device values remain available only in target-declared operand
positions; they do not control ordinary source topology. Runtime scan values
cannot select branches during linking.

ADR-0052 reserves a future explicit Hardware request under
`catseq.hardware.control`; `control.when(...)` is illustrative rather than a
frozen marker identity or signature. The namespace is not published until
Branch Region semantics, effect reconvergence, diagnostics, and RTMQ lowering
are designed. Hardware conditionals never fall back to ordinary CompileTime
selection. Compile-reachable `while` remains unsupported and has no staged
meaning.

Sync Phi remains in 0.3 for a Dynamic opaque Timing Contract. It is not evidence
that a hardware `if` is supported. If hardware conditionals are added after
0.3, they may reuse the existing Epoch reconvergence and equal-end-state rules,
but their source, arena, target-capability, and lowering semantics require a
separate decision.

This decision keeps Dynamic opaque-region semantics separate from future
Hardware conditional control.
