---
status: accepted
---

# Separate definition identity, revision, and specialization

A `DefinitionKey` deterministically identifies a source definition by Source
Bundle identity, canonical module name, qualified lexical name, and definition
kind. A compiler session interns that key as a dense `DefinitionId`; the integer
handle is stable only for the session and is used in arenas, tables, and
Definition DAG edges.

Editing a definition preserves its key and ID but creates a new immutable
`DefinitionRevision`. The revision carries normalized interface and
implementation digests. Comments, whitespace, and source spans do not affect
those semantic digests. An interface change invalidates caller resolution and
type facts; an implementation-only change preserves compatible caller type
facts while invalidating artifacts that depend on the changed implementation.

A `SpecializationKey` identifies one compiled variant of a definition revision
under compile-time structural arguments, structural portions of immutable
instance and hardware bindings, structurally consumed calibrations, intrinsic
schema versions, and dependency revisions. Runtime Slots, Environment Slots,
and other Link-time operands are excluded. The specialization cache therefore
answers whether that concrete compiled fragment already exists; it does not
provide source identity.

Persistent caches use deterministic Definition Keys and semantic digests rather
than session-local integer IDs.
