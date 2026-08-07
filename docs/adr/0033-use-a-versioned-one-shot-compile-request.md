---
status: accepted
---

# Use a versioned one-shot compile request

The shared Rust compiler accepts a versioned `CompileRequest` containing a
Source Bundle manifest, canonical entry key, Compile Environment, Target
Profile, deterministic Compiler Limits, zero or more Link Bindings, and an
incremental-cache location. Rust reads all source files itself; the request
contains no Python AST, Morphism object, callable, or live instance.

Compiler Limits have versioned defaults and may be overridden explicitly by the
PyO3 or CLI adapter. `max_compile_time_iterations` counts iterations across all
nested ordinary `for` specialization in the request, and `max_native_nodes`
counts allocations across the Morphism and Value Expression arenas. Each limit
is charged before the corresponding specialization step or arena allocation.
The versioned defaults are 100,000 iterations and 1,000,000 native nodes. They
bound host work but do not change a successful program's semantics and do not
participate in artifact identity. They are never inferred from transient free
memory. A limit diagnostic names the exhausted counter, current count, limit,
and explicit override field.

Rust owns the versioned `CompilerLimits` schema and exposes the same value type
through PyO3. The Python facade accepts it as
`Compiler(..., compiler_limits=...)`, and `Compiler.from_system()` reads an
optional `system.compiler_limits`. `catseqc` accepts
`--compiler-limits <path>` containing the same JSON schema. Python does not
duplicate the schema as a dataclass, and the Target Profile does not carry host
limits.

The response contains a deterministic artifact key, Link Schema, Python-free
relocatable artifact, optional OASM Call Plan for each supplied binding set,
structured diagnostics, and incremental reuse statistics. Link Bindings do not
participate in artifact identity, nor do Compiler Limits. A request without
bindings performs compile only; a request with many bindings compiles once and
links a scan batch.

The PyO3 extension and `catseqc` commands are adapters over the same Rust
request API. Production automation may use the native binary and a versioned
stdin/stdout encoding without requiring a resident service. Python consumes
the OASM Call Plan mechanically and performs no CatSeq analysis or scheduling.
