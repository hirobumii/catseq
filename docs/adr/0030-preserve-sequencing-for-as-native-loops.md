---
status: accepted
---

# Preserve sequencing for as native loops

A compile-reachable Python `for` that accumulates Morphism sequencing lowers to
a typed Loop Region and then a canonical Morphism `LoopNode`; it is not expanded
into repeated Serial children. The compatibility `repeat_morphism` spelling
lowers to the same node and no longer creates a Python/OASM black box.

A Loop Region represents its induction variable, range, loop-carried values,
body, and yielded Morphism. Its LoopNode retains the trip-count Value Expression,
one body reference, and Morphism Effect. Target lowering emits a hardware loop
when the target supports every induction-dependent operand. Unsupported dynamic
indexing or loop-carried behavior is a target capability error rather than
permission to silently unroll the program.

Pure Compile data loops that do not accumulate sequencing may still be
evaluated by the abstract evaluator. Native sequencing loops must have a valid
effect from one iteration boundary to the next; state-closed bodies are the
canonical safe case.
