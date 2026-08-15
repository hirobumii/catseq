---
status: superseded by Issue-52
---

# Separate Compiled Sequences from execution runtimes

CatSeq's low-level public workflow is a system-scoped Compiler producing an
immutable Compiled Sequence, followed by an Ethernet Runtime executing that
artifact. The runtime performs the private OASM encoding step before entering
the Rust execution state machine. CatSeq will not expose a long-lived mutable
`seq`, public OASM `assembler`, `run_cfg`, or `eth_intf` compatibility surface.

The ergonomic Python API is a thin facade over Rust-owned compiler artifacts,
configuration, validation, and execution state. Keeping the pinned Python OASM
encoder private preserves ADR 0003 and ADR 0046 without carrying OASM's
Python-native assembly compromises into the new API. A failed compilation
cannot leave an older program installed for an accidental subsequent run.
