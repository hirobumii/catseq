---
status: accepted
---

# Keep query providers pure

CatSeq query providers are deterministic functions of their key, declared input
Dep Nodes, and other queries. They may not directly read files, environment
variables, clocks, randomness, Python objects, mutable global registries, or
external devices. The request driver supplies source, Compile Environment,
Target Profile, and intrinsic facts through explicit input queries.

A provider returns a `QueryOutcome` containing an optional value and a stable
Diagnostic Set. Diagnostics are data with Source Anchors rather than immediate
output side effects. An entry-level diagnostics query aggregates reachable
outcomes, allowing a green cached result to reproduce diagnostics without
implementing rustc's general Query Side Effect replay machinery.

Providers may append into an engine-managed, session-owned arena segment. The
segment remains private and unreachable until the provider succeeds and the
query engine atomically publishes its handle. Failed or abandoned segments are
never hashed as results, registered as Work Products, or persisted. This keeps a
single append-only arena without copying nodes or exposing partial results.

Work Product files are likewise created in the private incremental session and
registered only by successful query outcomes. Deserializing a cached query
result may not execute another query or create new dependency edges. External
response emission and incremental-session finalization occur in the driver
after the requested root queries finish.

This deliberately implements a smaller semantic surface than rustc. General
query side effects and replay can be added only if a future compiler requirement
cannot be expressed as a query value or an engine-managed publication.
