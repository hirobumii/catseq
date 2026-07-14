---
status: accepted
---

# Defer hardware conditionals beyond 0.3

CatSeq 0.3 supports source `if` only when its predicate has Compile Value
Availability. Specialization evaluates the predicate, records its Structural
dependencies, and lowers only the selected arm. A predicate with Link or Device
availability is a compile error.

Consequently 0.3 introduces no Branch Region, canonical Branch node, or RTMQ
branch fragment. Device values remain available only in target-declared operand
positions such as native Loop induction variables; they do not control source
topology. Runtime scan values cannot select branches during linking.

Sync Phi remains in 0.3 for a Dynamic opaque Timing Contract. It is not evidence
that a hardware `if` is supported. If hardware conditionals are added after
0.3, they may reuse the existing Epoch reconvergence and equal-end-state rules,
but their source, arena, target-capability, and lowering semantics require a
separate decision.

This decision narrows the hardware-branch examples in the Value Availability,
Sync Phi, and Atomic Operation decisions to future behavior without changing
their 0.3 semantics for Dynamic opaque regions.
