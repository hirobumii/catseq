# Preserve Lane behavior, not its dataclass layout

CatSeq will preserve Lane construction from tuple or list inputs, value equality,
its tuple-valued `operations` interface, timing and state behavior, and existing
composition semantics. It will not preserve dataclass reflection, pickle output,
or the internal field layout, because treating the current tuple field as storage
would prevent a persistent representation from eliminating repeated historical
copies during composition.

Lane remains logically immutable. Composition creates a new persistent operation
root that may share the roots of its operands; it never writes a result into either
operand. A Lane may memoize its own materialized operation tuple on first access,
because repeated computation yields the same observable value.

Construction snapshots list, tuple, or iterable inputs into Lane-owned immutable
storage. Mutating an input list after construction does not change the Lane; public
operation access always returns a tuple. The previous aliasing of list inputs is
treated as an inconsistency, not a compatibility requirement.

Lazy storage does not defer validation. Duration compatibility, state continuity,
symbolic-operation restrictions, and other existing errors remain eager at Lane
construction or composition time; only tuple materialization is delayed.
