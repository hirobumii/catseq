---
status: accepted
---

# Adapt the rustc query architecture

CatSeq 0.3 implements a compiler-owned, reduced version of rustc's incremental
query architecture. It does not depend directly on rustc's private
`rustc_query_system` crates and does not make SQLite or a content-addressed blob
store the semantic foundation of incremental compilation.

Each query invocation has a `DepNode` consisting of a `DepKind` and a stable
fingerprint of its query key. Query execution records the exact dependency
nodes in read order. The persisted dep graph stores each node's key and result
fingerprints plus its ordered edge range in flat arrays. Session-local dense
indices are never treated as stable cross-session identities.

One compiler invocation loads the previous dep graph as immutable data while
building and streaming the current dep graph. `try_mark_green` finds a previous
node by its stable query-key fingerprint and checks its dependencies in their
original read order. A green node copies its node and edges into the current
graph without executing the query. A node with a changed dependency executes
again and compares its stable result fingerprint, so an unchanged semantic
result stops red propagation.

Persistence has three distinct layers. The dep graph and result fingerprints
are always eligible for persistence. Only query kinds explicitly marked for
on-disk caching serialize their values, and cache promotion preserves cached
values for green nodes that were not otherwise loaded. Large reusable compiler
outputs are indexed as Work Products rather than query-cache values;
CanonicalPrograms, RTMQ Fragment Templates, and Relocatable RTMQ Artifacts are
CatSeq's analogues of rustc code-generation work products.

The current session directory is private and locked until compilation
succeeds. Success finalizes and publishes it as immutable; an erroneous session
is invalid and cannot replace the previous usable session. Large aggregate
queries expose per-definition projection queries so their stable results form
change-propagation firewalls.

The first implementation follows rustc's algorithm and logical layout but not
all of its encoding optimizations. Variable-width edge packing, thread-local
index batches, and other physical compression are added only when CatSeq
profiles justify them.

References:

- <https://rustc-dev-guide.rust-lang.org/queries/incremental-compilation.html>
- <https://rustc-dev-guide.rust-lang.org/queries/incremental-compilation-in-detail.html>
- <https://doc.rust-lang.org/nightly/nightly-rustc/rustc_query_system/dep_graph/serialized/index.html>
- <https://doc.rust-lang.org/nightly/nightly-rustc/rustc_incremental/index.html>
