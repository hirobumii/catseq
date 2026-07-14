---
status: accepted
---

# Keep the Morphism arena free of Python syntax

The native frontend may use Source HIR and Typed Source HIR while it resolves
restricted Python, but the canonical Morphism arena is the first durable
CatSeq sequencing representation. No Python AST node, class attribute lookup,
`dataclasses.replace` operation, container, callable, or Python object may be a
Morphism arena node or payload.

Before Morphism arena lowering, the frontend:

- resolves service and template calls to stable `DefinitionId`s;
- resolves channel, service, and module references to typed native handles;
- evaluates Compile attribute accesses and structural control flow;
- eagerly normalizes supported dataclass construction and replacement;
- lowers scan inputs and supported arithmetic to native typed value
  expressions;
- desugars contextual channel bindings into CatSeq composition semantics.

The Morphism arena then contains only CatSeq sequencing nodes, definition and
instance references, Morphism Effects, and Atomic Operation payload references.
Symbolic scalar operands live in a separate native Value Expression Arena and
are referenced by `ValueExprId`. That arena contains typed constants, Runtime
Slots, and supported checked operations; it contains no source-HIR or Python
payloads.

Source HIR remains only in the compiler session's independent cache and
diagnostic database for incremental invalidation and rebuilding changed
definitions. A published compiler artifact owns only its Morphism Arena, Value
Expression Arena, native schemas, and native provenance tables. It neither
owns nor pins Source HIR, and production arena traversal never interprets it.
