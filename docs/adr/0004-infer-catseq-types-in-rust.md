---
status: accepted
---

# Infer restricted-Python CatSeq types in Rust

The CatSeq native compiler will not use Python execution or reflection as its
primary type system. After parsing source HIR, Rust collects reachable
definitions, resolves names, generates type constraints, unifies those
constraints, and produces Typed Source HIR before lowering Morphism structure
into the arena.

Type annotations are constraints rather than the only source of type
information. The compiler may infer unannotated local variables, service
fields, method parameters, and method results from constructor assignments and
reachable call relationships. Ambiguous or unsupported programs are compile
errors; the compiler does not fall back to importing or executing the module.

The Compile Environment supplies only facts that cannot be derived from the
restricted source bundle, including hardware mappings, calibration snapshots,
structural instance data, and signatures for registered external intrinsics.
Runtime scan values remain in Runtime Bindings and are not inputs to type
inference or specialization.

This makes Typed Source HIR a deterministic incremental-compilation boundary
and preserves a standalone Rust compiler path, at the cost of implementing a
CatSeq-specific type checker. The exact closed set of types and allowed
coercions will be decided separately before this milestone is implemented.

The production syntax frontend directly depends on revision-pinned
`nac3parser` and `nac3ast`. The CatSeq type checker does not depend on
`nac3core`: it adopts NAC3's useful organization of definition registration,
symbol resolution, constraint generation, union-find unification, and
aggregated diagnostics, but implements those mechanisms over CatSeq-owned
definitions and types. This avoids importing NAC3's LLVM, NumPy, general Python,
and ARTIQ semantics into the RTMQ compiler.
