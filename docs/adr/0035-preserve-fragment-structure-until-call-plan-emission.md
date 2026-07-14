---
status: accepted
---

# Preserve fragment structure until call-plan emission

Target lowering stores Relative RTMQ Fragments in a segmented native arena
rather than immediately flattening each board into an event vector. Fragment
nodes retain Event Ranges, template Instantiate references, variadic Serial and
Parallel composition, Loop, Sync Phi, and Epoch structure. Primitive events and
child references occupy flat tables.

Each definition specialization produces a target-specific Fragment Template
with per-board event ranges, a duration expression, board mask, Link Slot
dependencies, and provenance. Calling it creates an Instantiate node with
channel and value bindings and does not copy its event ranges. Associative
composition may be flattened within one specialization segment but never across
Instantiate, definition, Loop, Sync Phi, or Epoch boundaries.

Linking memoizes fragment summaries and recomputes only ancestors of affected
Value Expressions or bindings. A duration change may update later placement
without rebuilding unchanged sibling fragments; an operand-only change does
not update placement. The DAG is traversed and flattened by board and Epoch only
when the final OASM Call Plan is emitted.
