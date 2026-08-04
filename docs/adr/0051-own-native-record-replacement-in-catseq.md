---
status: accepted
---

# Own Native Record replacement in CatSeq

CatSeq 0.3 temporarily recognized `dataclasses.replace(...)` as compatibility
syntax for immutable updates of registered Native Records. That spelling made a
Python host helper appear to own a compiler operation and encouraged the
frontend to identify replacement by the callable's leaf name.

CatSeq now exposes `catseq.replace(record, **changes)` as a Compiler Special
Form. The Python definition is a compiler-only typed surface: calling it with
CPython raises `CompilerOnlyError`. The Rust Intrinsic Registry recognizes the
exact `catseq.replace` identity, not an arbitrary callable whose path ends in
`replace`.

The special form accepts one registered Native Record as its positional base
and named field updates. The frontend preserves the base's nominal record type,
validates every field name and value type against the Rust-owned schema, and
normalizes the operation into a complete immutable record before Morphism arena
publication. Compile-known changes become constants; Link changes remain Value
Expressions until RTMQ linking. No replacement operation survives in the
Morphism arena.

`dataclasses.replace` is a Host Module call and is rejected when
compile-reachable. User-defined functions named `replace` remain ordinary
source definitions and receive no Special Form semantics. Host Python may
still use dataclasses for host-owned configuration; this decision only removes
dataclasses from Native Record replacement semantics.
