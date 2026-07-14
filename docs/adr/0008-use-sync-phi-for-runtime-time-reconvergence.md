---
status: accepted
---

# Use Sync Phi for runtime time reconvergence

An opaque region, or a future hardware branch, may have a duration that cannot
be known at compile or link time. Padding such a region to a static maximum is
impossible when no sound maximum is available, and allowing later operations to
inherit a path-dependent absolute timestamp would break deterministic
cross-board scheduling. CatSeq 0.3 uses this rule for Dynamic opaque regions and
does not implement hardware conditionals.

The canonical arena therefore admits `NodeKind::SyncPhi`, represented by a
`SyncPhiNode`. Sync Phi is a control node, not a third Morphism composition
kind. Every participating board arrives at the rendezvous; a coordinator waits
for all arrivals and releases all participants into the next Epoch with one
shared runtime time origin.

Events are timestamped by `(EpochId, offset)`. Offsets within one Epoch remain
statically compiled and linked, but timestamps from different Epochs are not
directly comparable or subtractable. A Sync Phi release, rather than a
compile-time absolute timestamp, supplies the origin of the following Epoch.

The OASM Call Plan is consequently segmented by Epoch. Each segment identifies
an initial or `SyncPhiRelease` origin and contains board-grouped calls positioned
relative to that origin. The backend emits the arrive, wait, and release
protocol required by the target hardware.

Sync Phi merges arrival timelines only. It does not merge different hardware
states produced by control-flow paths. For every affected channel, all incoming
paths must have the same externally visible end state. A path with a different
state must perform an explicit recovery transition before arriving at Sync Phi;
otherwise compilation fails at that path's exit. CatSeq 0.3 does not introduce
a `StatePhi` or path-sensitive state union.

This creates an incremental timing cut: changing an uncertain region before a
Sync Phi does not invalidate relative scheduling after the Sync Phi. It also
requires a genuine rendezvous protocol. The current one-way master-trigger and
slave-wait implementation is a precursor but cannot handle uncertainty on an
arbitrary participating board without readiness or acknowledgement support.
