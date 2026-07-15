---
status: accepted
---

# Use a versioned one-shot compile request

The shared Rust compiler accepts a versioned `CompileRequest` containing a
Source Bundle manifest, canonical entry key, Compile Environment, Target
Profile, zero or more Link Bindings, and an incremental-cache location. Rust
reads all source files itself; the request contains no Python AST, Morphism
object, callable, or live instance.

The response contains a deterministic artifact key, Link Schema, Python-free
relocatable artifact, optional OASM Call Plan for each supplied binding set,
structured diagnostics, and incremental reuse statistics. Link Bindings do not
participate in artifact identity. A request without bindings performs compile
only; a request with many bindings compiles once and links a scan batch.

The PyO3 extension and `catseqc` commands are adapters over the same Rust
request API. Production automation may use the native binary and a versioned
stdin/stdout encoding without requiring a resident service. Python consumes
the OASM Call Plan mechanically and performs no CatSeq analysis or scheduling.
