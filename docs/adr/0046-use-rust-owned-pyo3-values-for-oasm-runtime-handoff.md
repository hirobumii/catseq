status: accepted
---

# Use Rust-owned PyO3 values for the OASM runtime handoff

CatSeq 0.3.1 will execute finalized OASM programs through the Rust runtime after
Python invokes the pinned OASM encoder. This does not change ADR 0003: native
compilation still ends at the OASM Call Plan. OASM assembly is a post-compiler
adapter, and physical execution is a separate runtime operation.

The assembled program, board endpoints, and Linux raw-Ethernet configuration
have one authoritative representation in `catseq-runtime`. `catseq-python`
exposes frozen PyO3 classes over those Rust values. Python code may invoke OASM,
extract finalized ICH words and the encoded reply endpoint, and construct the
native classes, but it will not define parallel dataclasses, duplicate runtime
validation, or serialize a required byte/JSON request between Python and Rust.

The execution entry accepts the native assembled-program and configuration
classes directly. Rust validates the complete topology before opening a raw
socket, releases the GIL for blocking execution, and returns Rust-owned
structured evidence through PyO3.

This keeps schema ownership, preflight rules, and physical execution in one
module while retaining OASM as the final instruction encoder. A future
persistence or remote-wire format would be a separate versioned interface; it
is not implied by the in-process PyO3 handoff.
