---
status: accepted
---

# Keep Compute bodies outside Typed Source HIR

CatSeq must recognize calls to reusable `@compute` functions while building
Typed Source HIR, but the pinned CatSeq NAC3 fork is the semantic authority for
their bodies and transitive Compute callees. Passing only a file path to a later
phase would allow that phase to parse different source from the source that the
frontend analyzed. Embedding NAC3 AST, CFG, or SSA in Typed Source HIR would
instead make CatSeq's Morphism frontend own a second representation of Compute
programs.

`@compute` therefore joins the exact-object registration authority already used
for compiler-visible definitions. A reachable explicit Compute call resolves to
that registered identity; the frontend does not discover Compute Functions by
name or infer them from undecorated helpers. Automatic Compute Regions use the
same downstream contract after outlining.

For one compilation request, the frontend freezes every reachable Compute
source unit in a session-owned Compute Unit Store. The pinned NAC3 fork parses
and validates the complete reachable Compute closure against those frozen units
before CatSeq publishes Typed Source HIR. Validation failure publishes neither a
partial HIR nor a cacheable success result.

On success, Typed Source HIR records only Compute definition/call identities,
Validated Compute Interfaces, value dependencies, work constraints, and source
provenance. The Compute Unit Store remains a sibling owned by the same compiler
session and survives until NAC3 has performed the downstream Compute code
generation required by that request. Later phases use the frozen units and must
not reopen ambient source files. The store is released with the request; the
persisted container for Compute input, final Wasm, and `ComputeManifest` remains
a separate #80 design decision.

The store retains the exact NAC3 typed compilation unit produced by validation.
Downstream Compute code generation consumes that same unit without reparsing or
retyping the frozen source. This makes the program accepted at the publication
barrier identical to the program later compiled, at the cost of retaining NAC3
request state until Compute code generation finishes. #82 delivers this
registration, validation, and request-lifetime handoff; it does not absorb
LLVM/Wasm generation.

This narrows earlier frontend decisions rather than replacing their CatSeq
domain rules. ADR 0004's CatSeq-owned type checker still owns Kernel, Morphism,
and Control source types, while Compute body typing is the deliberate
`nac3core` exception. ADR 0022's immediate normalization into CatSeq Source HIR
does not apply to Compute bodies. ADR 0023's compile reachability hands a
reachable Compute call to a separate NAC3-owned Compute closure. ADR 0029's
direct Typed Source HIR evaluation remains true for CatSeq topology; the Compute
Unit Store is neither an extra CatSeq HIR nor part of the native Morphism arena.

This keeps one immutable source authority throughout a compilation and keeps
Compute executable semantics out of CatSeq HIR. The cost is that Typed Source
HIR alone is insufficient for downstream Compute code generation: the compiler
request must carry its sibling Compute Unit Store until that work is complete.
