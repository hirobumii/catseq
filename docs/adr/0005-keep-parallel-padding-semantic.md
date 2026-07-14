---
status: accepted
---

# Keep Parallel Alignment semantic in the canonical arena

Every parallel Morphism has one shared end boundary. Its duration is the
symbolic maximum of its branch durations, and each shorter branch holds its
final state until that boundary. This Parallel Alignment rule remains true when
durations depend on Runtime Slots.

The canonical Rust arena stores the parallel composition and its children, but
does not append synthetic Identity nodes for branch padding. The Morphism effect
pass computes the shared duration and held states. Compatibility Lane views
materialize the same Identity operations, including generated provenance, and
RTMQ/OASM lowering emits waits or timestamp displacement when its target format
requires them.

This preserves the observable Morphism algebra while avoiding target-shaped
padding nodes, repeated padding in nested parallel trees, and scan-dependent
arena mutation. Downstream serial composition always begins at the shared
parallel boundary.
