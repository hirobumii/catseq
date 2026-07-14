---
status: accepted
---

# Track incremental dependencies with a query DAG

The native compiler is demand-driven. Parsing, module indexing, per-definition
HIR lowering and resolution, SCC type analysis, compile evaluation, and
specialization are memoized queries. While a query runs, it records the exact
definition revisions, earlier query results, intrinsic schemas, and individual
Compile Environment facts it reads.

Cache validation uses red-green propagation. An unchanged input reuses its
query result. If a changed input is recomputed but its normalized output
fingerprint remains equal, downstream queries remain green. A changed output
invalidates only queries reachable through recorded dependency edges. Runtime
Slot values never become query inputs.

The Query DAG is compiler-session metadata and is distinct from the program's
Morphism DAG. It uses dense native query handles and flat edge storage rather
than recursive objects. Whole-Compile-Environment digests and manually curated
transitive invalidation lists are not used as substitutes for actual dependency
recording.
