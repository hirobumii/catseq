---
status: accepted
---

# Store Source HIR in definition segments

The compiler session owns one logical `SourceHirStore`, segmented by
`DefinitionId`. Each definition revision occupies immutable ranges in flat node
and child-edge tables. Cross-definition operations refer to `DefinitionId`
rather than pointing into another definition's node range, and compiler passes
traverse nodes with explicit worklists.

Name resolution, inferred type, Value Availability, compile-time value, and
other semantic results live in side tables keyed by HIR node identity. Typed
Source HIR is the combination of an immutable Source HIR segment and its
complete semantic fact tables, not a copied typed syntax tree. Per-node lists
and recursive Rust objects are not part of the canonical storage model.

Changing one definition creates a replacement segment and fact set without
copying unchanged definitions. Source HIR remains compiler-session state for
analysis, diagnostics, and incremental invalidation; published Value Expression
and Morphism arenas contain no Source HIR references.
