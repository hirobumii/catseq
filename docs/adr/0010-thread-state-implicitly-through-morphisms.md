---
status: accepted
---

# Thread state implicitly through Morphisms

The native restricted language does not include `get_end_state`, `StateMap`, or
explicit state-map parameters between sequencing services. A Morphism is a
channel-bound state transformer: its Morphism Effect consumes the incoming
State Environment supplied by its Serial position and produces the outgoing
State Environment for the next child.

A Morphism Template has free channel slots but no source-visible incoming-state
slot. Binding its channel slots creates a Morphism whose state constraints and
transformations are evaluated in context. Entry roots obtain their initial State
Environment from declared hardware or service configuration.

Existing rb1-next patterns that compute `get_end_state(prefix)` and pass the
result to the next service are migrated to direct Serial composition. Service
signatures no longer accept explicit start-state maps, and helpers such as
state-seeded dictionary construction become context-sensitive Morphism builders.
The legacy Python runtime may retain `get_end_state` for debugging and
compatibility outside native compilation.

This makes state dependencies structural DAG dependencies, eliminates Lane
traversal and heterogeneous state-map types from the source language, and lets
incremental effect invalidation follow Serial edges directly. Native compilation
reports `get_end_state` as a migration error rather than creating a compatibility
intrinsic.
