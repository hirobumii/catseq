---
status: accepted
---

# Normalize Control around maximal Morphism islands

CatSeq's normalized Control embeds each maximal consecutive pure Morphism
subprogram as one `Lift`. The equation
`Lift(M >> N) ≡ Then(Lift(M), Lift(N))` is a semantic homomorphism law, while
normalization is oriented only from adjacent normal Lifts to `Lift(M >> N)`.
Diagnostic origins remain in the independent Origin Map rather than controlling
the semantic shape.

This orientation keeps Morphism Serial and Boundary Contract composition inside
the Morphism algebra, avoids duplicating Morphism ordering in Control, and gives
normalization a deterministic, terminating, and idempotent direction.

The first canonical core contains exactly:

```text
Control<B> ::= Return(Unit | Value(ValueRef<B>))
             | Lift(Morphism)
             | Then(Control...)
             | Fail(message)
```

`ValueRef<B>` is an opaque typed reference supplied by the independent value
layer. There is no canonical `ControlIdentity` or `Compute` node.

## Result discipline

`Lift(M)` has type `Control<Unit>`, and `Then` uses right-result sequencing like
Haskell `>>` or `*>`:

```text
M >> M                    -> M
M >> Control<B>           -> Control<B>
Control<A> >> M           -> Control<Unit>
Control<A> >> Control<B>  -> Control<B>
```

Sequencing does not implicitly preserve or accumulate a left result. Values
produced earlier remain ordinary SSA values and may be referenced by later
nodes, but a normalized Kernel Function exposes a final `B` only through an
explicit Control `Return(value)`. For example, a source dependent pair
`(capture >> readout, count)` normalizes schematically to
`Then(Lift(capture >> readout), Return(count)): Control<int>`.

There is no separate canonical `ControlIdentity` node. The effect-only
sequencing unit is `Return(Unit): Control<Unit>`, so normalization also applies:

```text
Lift(Id)                         -> Return(Unit)
Then(Return(Unit), C)            -> C
Then(C: Control<Unit>, Return(Unit)) -> C
```

An output-only `Control<B>` has no incoming `B` for a polymorphic identity node
to preserve. Introducing such a node would require an arrow-like input/output
type that this Control core deliberately does not have.

`Then` is variadic and stores one flat ordered child list. Associative source
spellings such as `(A >> B) >> C` and `A >> (B >> C)` therefore normalize to
the same `Then[A, B, C]`. An empty list reduces to `Return(Unit)`, a one-child
list reduces to that child, and nested `Then` nodes are flattened before
adjacent Lifts are fused. A `Fail` may only be the final child because it has no
Normal Continuation.

Because `Then` exposes only its rightmost result, every non-final `Return(value)`
is removed. This does not remove the value or its Schedulable Work: a later use
remains connected through the independent value graph, and ordinary dead-value
elimination remains a later optimization.

Normalization is a fixed bottom-up construction, not an unordered rewrite
loop. It normalizes children, flattens nested `Then`, rejects a no-normal-exit
child with a successor, removes non-final Returns, converts `Lift(Id)`, fuses
adjacent Lifts, and finally reduces empty or one-child lists. Reapplying this
procedure produces the same result.

This is a consequence of `>>` associativity, canonical equality, and the
accepted variadic Morphism Serial representation in ADR 0006 rather than a new
source-language choice.

## Failure boundary

The first core contains one concrete no-return computation,
`Fail(message)`. It has an explicit failure exit and no normal exit or result
value. Its `Control<B>` result parameter is determined by the enclosing type
context; CatSeq does not add a source-visible `Never` type merely to represent
this node.

Ordinary `Then` requires a normal continuation, so `Fail(message) >> C` is a
compile-time error at that composition boundary. This decision does not create
a generic terminal-kind hierarchy. Additional abrupt exits and the meaning of
`control.complete()` remain with the concrete Control forms that first require
and prove them.

## Orthogonal work and value graphs

`Compute` is not a canonical Control continuation node. Realtime scalar
computation, RWG preparation, predicate evaluation, dispatch, and other
Schedulable Work live in separate value and work dependency graphs. `Return`,
and later guards and anchors, reference their typed results and dependencies by
stable IDs.

This preserves the rule that Schedulable Work is placed from dependencies,
release, deadline, cost, and resource claims without moving the Logical
Timestamp. Encoding source assignments as adjacent Control `Compute` nodes
would incorrectly make Python statement order a temporal scheduling order.
The Device SSA, work payload, hardware-call, and function-summary contracts
remain owned by #57, #54, and #65; #67 only preserves their references while
normalizing Control continuation topology.

## Pure Morphism Parallel

After #38 validates Resource Support independence, `M | N` remains one pure
Morphism subprogram and its canonical Control embedding is `Lift(M | N)`. The
Control core does not introduce `ParallelControl`, repeat the Morphism
independence check, or expand the branches into separate Control children.
Control Parallel and its join semantics remain with #62.

Rigid anchors, logical cursor displacement, and value dependencies already
belong to the Morphism and work/value graphs. They do not create a speculative
extra normalization barrier between adjacent Lifts. A real Control node with
its own completion or join semantics is a boundary; no such future node is
invented in this minimal core.

## Source locations

Source locations do not participate in normalized Control equality, semantic
summaries, or semantic hashing. An independent Origin Map associates each
normalized node and relationship with every contributing Source Anchor and its
diagnostic role. Fusion therefore preserves the calls and operators that formed
one maximal Morphism Island without making line and column changes alter the
hardware program's semantic identity.

Diagnostics are first expressed using a stable diagnostic code and a semantic
subject, then resolved through the Origin Map. For an invalid
`Fail(...) >> readout`, the `>>` location is primary while both operands may be
reported as related locations. Source revisions still invalidate frontend
analysis through the normal source-dependency system; separating origins does
not permit stale source analysis to be reused.

## Considered options

- Expanding every Morphism Serial into Control `Then` was rejected because it
  destroys maximal Morphism islands and duplicates sequencing structure.
- Treating both directions as normalization rewrites was rejected because the
  rewrite system would not terminate.
- Preserving the left result when the right side is `Unit` was rejected because
  it makes `Unit` a sequencing special case and leaves two value-producing
  operands ambiguous.
- Accumulating every intermediate result into a product was rejected because it
  exposes unused values and makes result types grow with sequencing length.
- Keeping `ControlIdentity` distinct from `Return(Unit)` was rejected because
  the nodes have no semantic distinction for effect-only sequencing, while a
  result-preserving identity would require an input type absent from
  `Control<B>`.
- Introducing a generic `Terminal` enum or a source-level bottom type was
  rejected because the current slice has only one concrete no-return operation,
  `Fail`, and the other exit kinds do not yet have defined semantics.
- Keeping `Compute` as a Control continuation node was rejected because it would
  either serialize independently schedulable work or force #67 to define the
  scheduler contracts owned by the value, HAL, and Kernel Function slices.
- Expanding legal pure Morphism Parallel into a Control Parallel was rejected
  because it duplicates Morphism structure and pulls #62 join semantics into
  the core.
- Reserving an undefined "unrepresentable anchor boundary" was rejected until a
  concrete Morphism composition demonstrates a boundary that its existing
  Serial/value dependency representation cannot preserve.
- Including source positions in normalized equality or semantic hashes was
  rejected because moving equivalent source would change program identity.
- Retaining only one source position per fused node was rejected because it
  loses the other calls and operators needed for useful diagnostics.
