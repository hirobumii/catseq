---
status: accepted
---

# Use owner and projection query granularity

CatSeq follows rustc's owner and projection pattern instead of creating a Dep
Node for every Source HIR expression. Query granularity descends through module,
definition, recursive SCC, specialization, and target fragment boundaries.

Input query kinds expose module source text, individual Compile Environment
facts, and individual Target Profile facts. Module queries parse and index one
module. A `DefinitionHeader(DefinitionKey)` Projection Query shields consumers
from unrelated Module Index changes. Definition-owner queries lower and resolve
one Definition Revision and own its Source HIR Segment and Semantic Fact tables.

Type, availability, and dependency-role queries operate on a recursive SCC.
Specialization and Morphism Effect queries operate on a Specialization Key.
Target lowering produces an RTMQ Fragment Template per target and definition
specialization, while an entry query assembles the Relocatable Artifact from
those fragments.

Expression types, resolved names, availability, and local compile-evaluation
facts remain indexed tables inside the definition-owner result. They are not
separate cross-session queries. This bounds DepGraph size and avoids stable
cross-session identities for every expression while preserving definition-level
invalidation.

Linking an Artifact and a Link Binding digest is a lightweight batch-local query
and is not cached to disk by default. The persisted Relocatable Artifact and its
Slot-to-fragment reverse index provide the reusable boundary for scan updates.

As a result, if an entry composes independent definitions as `a >> b >> c` and
only `b`'s duration changes, the target fragments for `a` and `c` remain green.
The compiler rebuilds `b`'s fragment and reruns entry composition and relative
offset linking without lowering `a` or `c` again.
