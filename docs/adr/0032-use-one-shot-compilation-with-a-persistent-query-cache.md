---
status: accepted
---

# Use one-shot compilation with a persistent query cache

`catseqc` is a one-shot binary compiler, not a required daemon. Each invocation
loads the previous incremental session's dependency graph, stable query-key and
result fingerprints, selected serialized query results, and compiled work
products. It builds a new Query DAG while applying red-green validation, then
atomically publishes a replacement cache session on successful completion.

Cross-session cache records use deterministic Definition Keys and stable
fingerprints; dense Definition IDs, node IDs, and other session-local handles
are remapped when cached results are loaded. The compiler persists only native
results whose reuse exceeds serialization cost, such as definition HIR and
facts, template or arena segments, and relative RTMQ work products. Failed or
interrupted compilation does not publish a partial session.

Source compilation and scan linking remain distinct internal queries without
requiring a resident process. A compile-and-link request may contain many Link
Bindings and produce many OASM Call Plans from one relocatable artifact. An
adaptive scan may invoke a lightweight artifact-link command that does not load
or run the Python frontend. A resident worker remains an optional deployment
optimization, not part of compiler correctness or cache identity.
