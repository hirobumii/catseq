---
status: accepted
---

# Evaluate compile-visible globals lazily

The Module Index registers compile-visible top-level bindings as
`GlobalDefinition`s with stable definition identities, declared types,
initializer HIR, and source order. Reading a global from a compile-reachable
definition requests a memoized native initializer evaluation; the compiler
never executes a Python module body to construct its namespace.

A reachable initializer may use supported pure restricted expressions,
previously declared globals, Compile Class Schemas, and intrinsics. It may
produce a scalar, Channel ID, Compile Instance, native record, or template
handle. Its exact dependencies enter the Query DAG, and a dependency cycle is a
diagnostic rather than a partially initialized module. Compile-visible globals
cannot rely on mutable reassignment.

Unreachable top-level expressions, host imports and initializers, device setup,
and `if __name__ == "__main__"` remain unexamined host code. An unsupported
initializer is rejected only when a compiled definition actually requires its
value.
