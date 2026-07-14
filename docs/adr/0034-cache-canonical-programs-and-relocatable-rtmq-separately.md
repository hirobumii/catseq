---
status: accepted
---

# Cache canonical programs and relocatable RTMQ separately

The compiler produces two independently cached work products. A target-
independent `CanonicalProgram` owns the Python-free Morphism and Value
Expression arenas, native schemas and provenance, and completed Morphism
Effects. Target lowering consumes it under a Target Profile and produces a
target-specific `RelocatableRtmqArtifact`.

The relocatable artifact has already performed state/effect validation, Atomic
Schema lowering, board partitioning, instruction selection, and native Loop and
Sync Phi lowering. It retains Epochs, a board-fragment DAG, relative timing and
operand Value Expression IDs, relocation records, a Link Schema, provenance,
and reverse indexes from Link Slots through expressions to affected fragments.
It contains target operation identities rather than Python callables.

Linking binds Runtime and Environment Slots, evaluates only affected
expressions and fragment summaries, updates affected board/Epoch composition,
and emits an OASM Call Plan. A Target Profile change invalidates relocatable
RTMQ while preserving a compatible Canonical Program. Link Binding changes do
not rerun source analysis, Morphism specialization, state validation, or target
instruction selection.
