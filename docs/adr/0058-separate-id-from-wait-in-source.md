---
status: accepted
---

# Separate Id from Wait in source

CatSeq exposes `Id()` as the zero-argument Morphism sequencing unit and
`Wait(duration)` as explicit logical cursor displacement. The overloaded
`identity(duration)` spelling is removed without a compatibility alias: it
conflated the algebraic unit with nonzero timing, required a unitless-zero
typing exception, and obscured the canonical `Id`/`Wait` distinction.

`Wait` always requires an actual `Duration`; a bare numeric zero is not a
Duration. A `Wait` whose typed Duration expression is semantically proven zero
may normalize to `Id` during frontend elaboration. Typed Source HIR only records
the distinct source intrinsic and its typed arguments; #77 owns that later
Morphism construction and normalization.
