---
status: accepted
---

# Remove strict serial composition

CatSeq's restricted Morphism language has one Serial composition operator:
`left >> right`, which threads the left Morphism's outgoing State Environment
into the right Morphism's incoming environment and validates the resulting
composition. The public `@` operator, StrictSerial HIR kind, and Strict boundary
policy are removed together in a dedicated compatibility change rather than as
part of Hardware loop implementation.

No executable Morphism `@` consumer remains in CatSeq or the checked rb1-next
and rb1-rtmq sources; the only apparent downstream examples are inert docstring
text, while real sequences use `>>`. Keeping a second operator would therefore
expand every composition-aware feature, including Hardware loop back-edges,
without a demonstrated user requirement. Removing it accepts a public syntax
break in exchange for one compositional rule and a smaller compiler model.
