---
status: accepted
---

# Use a rustc-style stable hashing context

CatSeq computes separate 128-bit stable fingerprints for query keys and query
results. Every persistent fingerprint is produced through a
`StableHashingContext` that maps session-local identities to their stable
semantic forms before hashing.

Definition IDs map to Definition Keys, Compile Instance IDs map to stable
instance keys, and Source HIR node IDs map to an owning Definition Key plus a
local node identity. Morphism and Value Expression IDs hash their node kind,
typed payload, and already computed child fingerprints rather than their arena
indices. DAG hashing follows deterministic iterative order and does not recurse
through Rust objects.

Semantic fingerprints exclude pointers, allocation and map iteration order,
dense arena or definition IDs, comments, whitespace, absolute source spans, and
Python object identity. They include semantically ordered operations and
children, exact typed scalar values, normalized definition interfaces or
implementations, Structural bindings, and the exact intrinsic, target, and
environment facts read through Dep Nodes.

Raw Source Text remains an input fingerprint. A whitespace-only edit therefore
makes that input red and reruns parsing, but the parser's semantic result may
retain its previous fingerprint and stop propagation. The current parse result
still owns current spans. Persisted Work Products refer to stable Source Anchors
rather than absolute byte offsets so diagnostics can resolve against the
current source session.

The cache file header contains the compiler build identity and encoding version.
An incompatible build rejects the previous incremental session as a unit. ABI,
intrinsic, Target Profile, and Compile Environment changes remain explicit
input Dep Nodes rather than being indiscriminately salted into every query key.

This follows rustc's stable-ID and stable-result-fingerprint model while keeping
the specific CatSeq canonicalization rules compiler-owned.
