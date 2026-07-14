---
status: accepted
---

# Use immutable service instances and registered phase frames

Service and module instances in the native compiler are immutable Compile-time
entities. Each has a stable `InstanceId`; `self` is an instance handle, and a
method call resolves statically to `(InstanceId, DefinitionId)`. Class and
instance attributes are resolved before Morphism arena lowering to constants,
channels, registered configuration values, or other immutable instance handles.
The compiled language cannot mutate an instance or a nested Python object.

`MWModule._tracker.phase` is not an instance field in native semantics. It is
the logical reference phase of one coherent drive group. A module declares a
`PhaseFrameDef` with semantic member roles such as I and Q. The Compile
Environment supplies a `PhaseFrameBinding` from those roles to physical
channels and calibrated offsets, producing the stable `PhaseFrameId` used by
the compiler. The frame is neither a program-global phase nor a copy of each
channel's physical absolute phase.

Definition collection assigns a stable identity to each `PhaseFrameDef`, and
Compile Environment binding allocates `PhaseFrameId` before Morphism arena
lowering. Typed Source HIR resolves legacy tracker access or native phase
operations to that ID. The Morphism arena then stores only the ID in frame-read
and frame-update effects, together with native `ValueExprId` operands. Serial
composition threads the frame environment. Target lowering maps the resulting
logical frame phase and calibrated offsets to physical channel operands;
hardware oscillator phase continuity remains part of the channel/Atomic
Operation model.

The compiler never infers frame membership by observing which channels a
service method happens to update, and the board-only hardware map does not own
coherent-control semantics. Two services sharing one bound module resolve to
the same `PhaseFrameId`; two bindings of the same module definition to distinct
coherent hardware groups receive distinct IDs.

A high-level coherent operation updates its phase frame once even if target
lowering later emits events for several member channels. Parallel operations on
different frames are independent. Two parallel operations claiming the same
frame are a resource conflict, not a state merge.

Mutable caches, counters, lifecycle state, properties, and other host-object
behavior are outside the native sequencing language. Existing source spelling
for the phase tracker may be recognized during migration, but no Python class,
tracker object, or field access survives in either native arena.
