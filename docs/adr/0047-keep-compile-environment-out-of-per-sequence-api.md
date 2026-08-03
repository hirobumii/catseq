---
status: accepted
---

# Keep the Compile Environment out of the per-sequence API

CatSeq retains the Compile Environment as the immutable source-external context
for hardware mappings, calibration facts, and intrinsic bindings, but ordinary
experiment compilation will not accept a hand-written environment dictionary.
System or compiler setup owns this context once and reuses it across sequence
compilations. Physical interface, chassis, and board-node settings belong to the
Ethernet Runtime instead, preserving a strict boundary between compilation and
execution.
