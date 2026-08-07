---
status: accepted
---

# Declare and recheck per-board ICH capacity

A Board ICH Program can be measured exactly only after the private OASM assembly
bridge has produced its ordered instruction words. CatSeq therefore uses two
independent capacity gates: program finalization checks the capacity declared by
the Target Profile used for compilation, and the Rust runtime checks the
separately configured physical endpoint again immediately before download.
Neither host Compiler Limits nor a capacity constant exported by an OASM core
substitutes for either gate.

Target Profile schema version 2 requires `instruction_capacity_words` in every
board entry, with no inferred or compatibility default. Schema version 1
profiles are rejected rather than upgraded implicitly. The bundled RTMQ v2
profile declares 131,072 words for every existing Main, RWG, and RSP entry,
matching their documented `W_ICH = 17` capacity.

The Rust-owned Compiled Sequence retains an immutable per-board ICH Capacity
snapshot from the exact Target Profile used for that compilation. It does not
reload a profile during assembly. A physical endpoint may expose more capacity
than the retained declaration, but an endpoint smaller than the finalized
program always fails the physical check even when profile validation passed.

`EthernetRuntime.prepare(compiled)` is the public, side-effect-free program
finalization boundary. It binds the runtime reply endpoint, invokes the private
OASM assembly bridge, checks every Board ICH Program against the retained
capacity snapshot, and validates runtime topology and physical capacities
without downloading or executing anything. `EthernetRuntime.run()` delegates
to `prepare()`, and the Rust runtime repeats physical handoff validation
immediately before download. `Compiler.compile()` remains independent of
physical reply routing; compile-only deployment validation calls `prepare()`
against the intended runtime.

The high-level Ethernet Runtime accepts explicit Rust-owned `BoardEndpoint`
values whenever a physical route needs a nonstandard channel or capacity. Its
existing `{address: node}` mapping remains a compatibility shorthand only for
the bundled RTMQ hardware and normalizes to download channel zero and 131,072
instruction words. Custom physical targets must use explicit endpoints; the
shorthand is not a general capacity inference rule.

Preparation failures use a separate Rust-owned `ProgramPreparationError`
contract rather than a Python `ValueError`, compile error, or physical runtime
failure. Capacity diagnostics carry a stable code, logical board, actual word
count, applicable limit, and whether that limit came from the retained profile
or the physical endpoint; topology failures use the same structured error
family. `run()` propagates a preparation error unchanged before opening a
socket or sending a frame.

This cross-cutting target/runtime work is tracked separately from staged
control. Full ordinary `for` specialization depends on it because specialization
can enlarge a Board ICH Program, while the immediate fail-closed guard for
silently erased source loops does not.
