---
status: accepted
---

# Use ordinary Python control for CompileTime staging

CatSeq treats ordinary compile-reachable Python `for` and `if` as CompileTime
compiler syntax. Their control inputs must be Compile-known, and specialization
evaluates the selected iterations or arms before canonical Morphism
construction. This preserves the source intuition and compatibility of the
0.2.4 Python-built Morphism model: ordinary Python control constructs source
topology rather than requesting target control flow.

Hardware Control Execution is reserved for explicit compiler-owned special
forms under `catseq.hardware.control`. The following spellings are illustrative,
not a published interface:

```python
from catseq.hardware import control

for index in control.range(0, count):
    result = result >> body(index)

if control.when(predicate):
    result = result >> enabled_path()
```

When Hardware control is designed, its compiler-owned markers must be recognized
by exact resolved definition identity. Import aliases resolving to a marker may
retain its meaning, while a local function with the same leaf name, a shadowing
binding, or an unrelated suffix match must not. This ADR reserves the namespace
and the explicit-selection rule without freezing marker identities, signatures,
or diagnostics. Value Availability and target capability validate a selected
domain but never switch it.

The first staged-control delivery implements only ordinary CompileTime control.
It does not publish a `catseq.hardware.control` Python namespace or register the
reserved identities. The spellings above record the future language boundary
without freezing marker signatures or diagnostics before Hardware control is
designed. Source Hardware `for` and `if` execution is not implemented in this
delivery.

Delivery starts with a separately grabbable P0 fail-closed guard for the current
silent loop erasure. After CompileTime condition selection, the guard rejects a
source `for` statement only when it lies on the selected specialization path;
loops in unselected paths remain subject to parsing, name resolution, and type
checking without triggering the guard. This safety issue has no dependency on
Compiler Limits, ADR-0054, or the full loop evaluator and is replaced when
ordinary `for` specialization lands.

The implementation then establishes ordinary CompileTime `if`, the
Specialization Environment, and CompileTime Completion as one independent
foundation before adding iteration. The first `for` tracer specializes
`range(Int64 @ Compile)` end to end, including nesting and all completion modes;
it depends on that foundation, the separate Compiler Limits issue, and
ADR-0054's capacity delivery. A later iterable extension adds direct
`FixedAggregate @ Compile` iteration, static comprehensions, filters, and name
destructuring. Conditional expressions belong to the `if` foundation, while
comprehension filters belong to the fixed-aggregate extension.

Ordinary `range` accepts only `Int64 @ Compile` operands and uses Python's one-,
two-, and three-argument normalization within that scalar domain. `Bool`,
objects with an `__index__` protocol, and source integers outside Int64 are
rejected. These intrinsic semantics apply only when the callable resolves to
`builtins.range`; an alias resolving to that definition is accepted, while a
shadowing or unrelated function named `range` is an ordinary call. Empty and
reverse-empty ranges have zero iterations, negative steps are valid, and a zero
step is an error. Normalization may use a wider internal count so valid Int64
endpoints do not overflow the compiler, but every visible induction value
remains Int64 and arithmetic overflow is diagnosed. Ordinary iteration over an
ordered, homogeneous `FixedAggregate @ Compile` preserves its fixed order.
Tuple and list values and statically evaluated comprehensions may provide that
aggregate; sets, mappings, generators, heterogeneous aggregates, and
host-runtime-dependent order are not part of the restricted source contract.

Ordinary `if` requires `Bool @ Compile`. Both arms remain subject to parsing,
name resolution, and type checking, while specialization, Morphism lowering,
resource validation, and target validation retain only the selected arm.
Boolean `and` and `or` accept only Bool operands and evaluate left to right with
short-circuit semantics. Every operand is parsed, resolved, and type checked,
but only the evaluated prefix contributes Value Availability. Consequently,
`False and link_bool` is Compile-known false, whereas `True and link_bool`
remains Link and cannot select an ordinary `if` arm.
Chained comparisons likewise evaluate operands once from left to right and stop
after the first false comparison; an unevaluated suffix is statically checked
without contributing availability.
Compile-reachable `while` remains outside the restricted source language and is
rejected before staging; this ADR assigns it no CompileTime or Hardware meaning.
Ordinary `for` implements Python `break`, `continue`, and loop `else` semantics.
Every entered iteration is charged before its body; `continue` ends that body,
`break` terminates the loop and suppresses its `else`, and normal exhaustion,
including an empty iterable, executes the `else`. Conditional expressions and
comprehension filters use ordinary CompileTime selection. All source paths are
parsed, resolved, and type checked, while only the path selected by
specialization enters Morphism, resource, and target validation.

A `return` reached through selected CompileTime control immediately completes
the current source definition. It suppresses any enclosing loop `else`, all
remaining iterations, and every later statement in that definition. This
completion propagates through arbitrarily nested CompileTime `if` and `for`
regions. A `return` in an unselected path still participates in name resolution
and type checking but does not complete specialization.

CompileTime control updates a compiler-owned Specialization Environment by
local rebinding. A body may assign a simple local name, destructure a
fixed-arity tuple or list pattern containing only local names, or use augmented
assignment on a simple local name. Each entered iteration observes the bindings
produced by the preceding iteration, which supports Morphism accumulators such
as `result = result >> body(index)`. Attribute and subscript assignment,
deletion, and calls whose meaning depends on mutating a Compile-known object's
internal state remain unsupported. Specialization does not emulate CPython
object mutation. CompileTime control does not introduce a block scope. After a
nonempty loop, its target and body rebindings retain the values from the actual
exit path. An empty loop preserves any prior bindings and does not create its
target; a later read of a name that remains unbound is a source-provenanced
compile error. CompileTime `if` follows the same function-local binding rule for
its selected arm.

All ordinary CompileTime control in one compile request shares two deterministic
Compiler Limits. `max_compile_time_iterations` is charged before every
specialized `for` iteration, including iterations nested under another loop.
`max_native_nodes` is charged before every Morphism or Value Expression arena
allocation. Exceeding either limit is a source-provenanced compiler-resource
diagnostic, not a semantic fallback. The limits have fixed versioned defaults,
100,000 iterations and 1,000,000 native nodes. Both may be overridden
explicitly, are never derived from free memory, and do not participate in
artifact identity. A diagnostic names the exhausted counter, current count,
configured limit, and override field.

Target deployability is governed independently by the per-board ICH Capacity
contract in ADR-0054. Compiler Limits and ICH Capacity are not interchangeable:
the former bounds host work, while the latter rejects a finalized target program
that cannot fit its board. The full ordinary `for` specialization delivery
depends on that generic capacity contract; an immediate fail-closed guard for
silently erased source loops does not.

The `catseq.compile_time` namespace is not introduced. Ordinary Python control
already provides its intended meaning, so a second spelling would weaken the
single explicit boundary between CompileTime and Hardware. The reserved
`catseq.hardware.control` namespace is likewise not published in this delivery.
Kernel bodies are not executed by CPython, so direct host-call behavior is not a
language acceptance criterion.

The existing `repeat_morphism` API remains an explicit Hardware compatibility
path with its permissive 0.2.4 behavior. New Hardware control representation,
validation, target capabilities, and lowering are outside this decision and the
current implementation scope.
