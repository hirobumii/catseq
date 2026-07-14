---
status: accepted
---

# End CatSeq 0.3 native compilation at the OASM Call Plan

CatSeq 0.3 will implement restricted-source parsing, service resolution,
specialization, Morphism analysis, relative RTMQ lowering, multi-board linking,
and OASM Call Plan generation in Rust. The existing Python OASM assembler will
remain the final encoding adapter because replacing the full assembler would
expand 0.3 beyond the compiler upgrade; direct Rust generation of RTMQ binaries
is a later backend replacement. Python performs no scheduling or CatSeq semantic
analysis after receiving the call plan.

The OASM Call Plan may contain multiple Epoch segments. Calls after a Sync Phi
use offsets from its runtime release rather than a link-time global absolute
timestamp; the Python adapter mechanically encodes the synchronization protocol
and relative calls without deciding their timing semantics.
