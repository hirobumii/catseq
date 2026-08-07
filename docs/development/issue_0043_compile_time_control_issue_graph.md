# Issue 43 publication record: Make ordinary Python control CompileTime

Published on 2026-08-07. GitHub issue 43 is the tracker; issues 45, 46, 48, and
49 are its sub-issues, while issues 44 and 47 are independent blockers. This
record preserves the approved decomposition and decision-rich briefs.

## Published tracker design

### What this tracks

Define and implement one source-language contract in which ordinary Python
`for` and `if` inside compile-reachable CatSeq source are CompileTime compiler
syntax. Only future explicit compiler-owned special forms under the reserved
`catseq.hardware.control` namespace may request Hardware control execution.

The current issue states the reverse contract and mixes CompileTime evaluation,
new Hardware loop lowering, future Hardware branches, host resource limits, and
target capacity into one agent-sized issue. It must become a tracking issue over
independently verifiable deliveries. The tracker itself must not carry
`ready-for-agent`.

### Current correctness bug

At commit `e3735a4357ec511bf243e84aa7a726c9053c4514`, a reachable ordinary source
loop can compile successfully while its Morphism body is erased:

```python
def source_for(count: int = 3) -> Morphism:
    result = identity(0)
    for _ in range(count):
        result = result >> short_pulse()
    return result
```

For a four-cycle `short_pulse()`, the current result has zero logical duration
and no OASM calls. The required CompileTime result for `count == 3` is the same
Serial Morphism as three manually written calls, with twelve cycles of logical
duration. Until specialization exists, the selected loop path must fail closed
with source provenance rather than return identity.

### Language contract

| Source construct | Requirement | Compile result |
|---|---|---|
| ordinary `for ... in range(...)` | Int64 operands at Compile | specialize iterations before Morphism construction |
| ordinary `for ... in values` | ordered homogeneous FixedAggregate at Compile | specialize one body per element in fixed order |
| ordinary `if predicate` | Bool at Compile | specialize only the selected arm |
| ordinary `while` | unsupported | source-provenanced error before staging |
| future explicit Hardware marker | outside current delivery | reserved by ADR-0052 only |
| `repeat_morphism(body, count)` | existing compatibility API | retain permissive 0.2.4 Hardware behavior |

The detailed semantics are owned by ADR-0052 and the glossary in `CONTEXT.md`:

- all source paths are parsed, name-resolved, and type checked;
- only the selected path enters specialization, Morphism/resource validation,
  and target validation;
- `and`, `or`, and chained comparisons short-circuit left to right while
  statically checking unevaluated operands;
- loops support nesting, `break`, `continue`, `else`, and early `return`;
- selected control updates compiler-owned local bindings and never mutates a
  CPython object graph;
- control follows Python function scope along the selected path;
- `range` supports one, two, and three Int64 arguments, empty and reverse-empty
  ranges, negative steps, and a zero-step diagnostic;
- FixedAggregate iteration accepts ordered homogeneous tuples, lists, and
  statically evaluated comprehensions, and rejects sets, mappings, generators,
  heterogeneous aggregates, and host-dependent ordering.

### Independent safety constraints

The full range delivery is blocked by two generic safety issues:

1. Rust-owned Compiler Limits with cumulative request-level
   `max_compile_time_iterations` and `max_native_nodes` counters, as recorded in
   ADR-0033.
2. Required per-board Target Profile capacity, retained capacity snapshots,
   side-effect-free `EthernetRuntime.prepare()`, and physical pre-download
   revalidation, as recorded in ADR-0054.

Compiler Limits protect the host compiler. ICH Capacity protects each target
board. Neither substitutes for the other.

### Non-goals

- Do not publish `catseq.hardware.control` in this delivery.
- Do not implement a Hardware Loop Region, Hardware Branch Region, LoopIndex,
  state/effect closure proof, nested Hardware loop lowering, or target Hardware
  control capability.
- Do not harden or reinterpret the existing `repeat_morphism` behavior.
- Do not introduce `catseq.compile_time`; ordinary Python control is the
  CompileTime spelling.
- Do not execute kernel bodies with CPython.
- Do not make ADR-0034 / issue 33's future CanonicalProgram a prerequisite for
  the immediate guard or the current NativeArenas specialization path.
- Do not combine removal of strict serial `@` composition with this tracker;
  ADR-0053 records that separate compatibility change.

### Published issue graph

```text
#46  Fail closed on selected source-for paths             (no dependency)
#44  Add Rust-owned Compiler Limits                       (independent blocker)
#47  Declare and recheck per-board ICH capacity           (independent blocker)
#45  Specialize ordinary CompileTime if                   (no dependency)

#44 + #47 + #45
    |
    v
#48  Specialize ordinary range for statements
    |
    v
#49  Iterate ordered Compile-time FixedAggregates
```

Issues #45, #46, #48, and #49 are sub-issues of this tracker. Issues #44 and
#47 are cross-cutting compiler/runtime issues linked as native GitHub blockers.
Issue #48 replaces the temporary guard from #46; it does not need #46's
implementation as a code dependency.

### Tracker acceptance criteria

- [ ] ADR-0052, ADR-0054, the amended ADR-0030/ADR-0041, and `CONTEXT.md` use the
      same CompileTime/Hardware vocabulary.
- [ ] The selected-path guard prevents the reproduced zero-duration successful
      compile before full loop specialization ships.
- [ ] Compiler Limits and both ICH capacity gates are delivered and tested.
- [ ] Ordinary CompileTime `if` owns selected-path specialization, local
      bindings, short-circuit evaluation, and early return.
- [ ] Ordinary `range` loops specialize before Morphism construction and cover
      nesting plus every completion mode.
- [ ] Ordered homogeneous FixedAggregate iteration and static comprehensions
      use the same loop evaluator.
- [ ] Public integration tests compare specialized output with manually written
      Serial Morphisms and prove that no Hardware Loop node or marker remains.
- [ ] User documentation explains that kernel control is compiler-evaluated and
      that kernel bodies are not executed by CPython.
- [ ] The tracker has `enhancement` but not `ready-for-agent`; only independently
      grabbable, dependency-satisfied implementation issues receive
      `ready-for-agent`.

## Published child and blocker briefs

### #46. Fail closed on selected source-for paths

Labels: `bug`, `ready-for-agent`.

Reject an ordinary `for` statement when it lies on the path selected by current
CompileTime condition evaluation and would otherwise be erased during Morphism
lowering.

#### Concrete example

```python
def broken(count: int = 3) -> Morphism:
    result = identity(0)
    for _ in range(count):
        result = result >> short_pulse()
    return result

def dead_loop() -> Morphism:
    if False:
        for _ in range(3):
            return short_pulse()
    return identity(0)
```

`broken()` must fail at the `for` source anchor. `dead_loop()` must still parse,
resolve, and type-check the unselected body but must not trigger the temporary
guard.

#### Acceptance criteria

- [ ] The public reproducer fails instead of returning a successful empty plan.
- [ ] The diagnostic contains the source module, line, and column and states
      that ordinary `for` specialization is not implemented yet.
- [ ] A loop in an unselected CompileTime arm does not trigger the guard.
- [ ] A malformed name or type in that unselected loop is still diagnosed.
- [ ] Existing loop-free compilation output is unchanged.

#### Blocked by

None.

### #44. Add Rust-owned Compiler Limits

Labels: `enhancement`, `ready-for-agent`.

Implement the versioned `CompilerLimits` contract from ADR-0033 once across the
Rust request driver, PyO3 `Compiler`, `Compiler.from_system()`, and `catseqc`.

#### Concrete example

```python
limits = CompilerLimits(
    max_compile_time_iterations=2,
    max_native_nodes=1_000_000,
)
compiler = Compiler(
    source_root=source_root,
    channels=channels,
    compiler_limits=limits,
)
compiler.compile(three_iteration_sequence)
```

Once ordinary range specialization consumes the counter, the third entered
iteration must fail before its body. Existing arena construction must already
consume `max_native_nodes` in this issue.

#### Acceptance criteria

- [ ] Rust owns one versioned schema with fixed defaults of 100,000 iterations
      and 1,000,000 native nodes.
- [ ] Limits are charged cumulatively per Compile Request before work occurs.
- [ ] The native-node counter covers both Morphism and Value Expression arenas.
- [ ] PyO3 exposes the Rust-owned value without a Python dataclass.
- [ ] `Compiler(..., compiler_limits=...)`, optional
      `system.compiler_limits`, and `catseqc --compiler-limits <path>` use the
      same schema.
- [ ] A diagnostic names the counter, current count, configured limit, source
      anchor, and override field.
- [ ] Limits never derive from free memory and do not enter artifact identity.
- [ ] A failure publishes no partial artifact or cache entry.

#### Blocked by

None.

### #47. Declare and recheck per-board ICH capacity

Labels: `enhancement`, `ready-for-agent`.

Implement ADR-0054 as a generic target/runtime safety contract.

#### Concrete example

```python
profile = rtmq_v2_profile()
profile["boards"]["main"]["instruction_capacity_words"] = 2

compiled = Compiler(
    source_root=source_root,
    channels=channels,
    target_profile=profile,
).compile(sequence_larger_than_two_words)

runtime.prepare(compiled)  # ProgramPreparationError before any network I/O
```

The same prepared Board ICH Program must also fail when its explicit physical
`BoardEndpoint` capacity is smaller than its word count, even if the retained
profile capacity is larger.

#### Acceptance criteria

- [ ] Target Profile schema version 2 requires
      `instruction_capacity_words` on every board; v1 and missing fields fail
      without an inferred migration value.
- [ ] The bundled profile declares 131,072 words for all existing Main, RWG,
      and RSP entries.
- [ ] Compiled Sequence retains an immutable per-board capacity snapshot from
      its exact profile.
- [ ] `EthernetRuntime.prepare(compiled)` assembles and validates without
      opening a socket or sending a frame, and `run()` delegates to it.
- [ ] The Rust runtime independently rechecks physical endpoint capacity
      immediately before download.
- [ ] Explicit Rust-owned `BoardEndpoint` values support custom channel and
      capacity; the existing route mapping remains only the bundled-hardware
      131,072-word shorthand.
- [ ] Structured `ProgramPreparationError` evidence contains a stable code,
      board, word count, limit, and profile-versus-endpoint source.
- [ ] A physical endpoint above the profile declaration is accepted when the
      program fits both; an endpoint below the program size always fails.

#### Blocked by

None.

### #45. Specialize ordinary CompileTime if

Labels: `enhancement`, `ready-for-agent`.

Replace the ad-hoc Morphism-lowering `if` special case with a selected-path
specialization stage that owns the Specialization Environment and CompileTime
Completion.

#### Concrete example

```python
def guarded(enabled: bool = True) -> Morphism:
    result = identity(0)
    if enabled:
        result = result >> short_pulse()
    else:
        return identity(0)
    return result
```

`guarded(True)` specializes to the pulse path. `guarded(False)` returns from the
selected `else` arm. Neither result retains a branch node.

#### Acceptance criteria

- [ ] An ordinary `if` requires Bool at Compile; Link or Device predicates fail
      with source provenance.
- [ ] Both arms parse, resolve, and type-check, while only the selected arm
      enters Morphism/resource/target validation.
- [ ] `and`, `or`, and chained comparisons short-circuit left to right, with
      path-sensitive availability and static checking of unevaluated operands.
- [ ] Conditional expressions use the same selected-path evaluator.
- [ ] Simple local assignment, fixed-name destructuring, and simple-name
      augmented assignment update compiler-owned bindings.
- [ ] Attribute/subscript assignment, deletion, and mutation-dependent calls are
      rejected.
- [ ] Selected early `return` completes the current source definition and skips
      later statements.
- [ ] Function-scope binding and source-provenanced unbound-name behavior match
      ADR-0052.
- [ ] No CPython execution is used to evaluate the source body.

#### Blocked by

None.

### #48. Specialize ordinary range for statements

Label while blocked: `enhancement`.

Extend the specialization stage with ordinary `for ... in range(...)`, using
the shared environment, completion model, and Compiler Limits.

#### Concrete example

```python
def staircase() -> Morphism:
    result = identity(0)
    for width in range(1, 4):
        result = result >> {ttl0: pulse(cycles(width))}
    return result
```

The result must equal three manually written pulses with widths one, two, and
three cycles. No Loop node or OASM loop marker may remain.

#### Acceptance criteria

- [ ] Range operands are Int64 at Compile; Bool, `__index__`, and out-of-domain
      integers fail.
- [ ] Range normalization is selected by resolved `builtins.range` identity;
      resolved aliases work and shadowed leaf names receive no intrinsic
      treatment.
- [ ] One-, two-, and three-argument forms, empty and reverse-empty ranges,
      negative steps, and zero-step errors match ADR-0052.
- [ ] Each visible induction value is Int64; internal count calculation cannot
      overflow valid Int64 endpoints.
- [ ] Every entered iteration consumes the cumulative iteration budget before
      its body.
- [ ] Nested loops have no separate semantic depth limit and share both request
      counters.
- [ ] `continue`, `break`, loop `else`, and early `return` propagate exactly as
      specified, including empty-loop `else`.
- [ ] Loop targets and body bindings retain Python function-scope values along
      the actual exit path.
- [ ] The public silent-erasure reproducer returns twelve cycles for count three
      and matches manual Serial composition.
- [ ] No Hardware Loop node, marker, or fallback is produced.
- [ ] `EthernetRuntime.prepare()` rejects a specialized Board ICH Program that
      exceeds its retained profile capacity.

#### Blocked by

- #44
- #47
- #45

### #49. Iterate ordered Compile-time FixedAggregates

Label while blocked: `enhancement`.

Extend ordinary `for` specialization from ranges to deterministic fixed
aggregates without introducing Python's runtime iterator protocol.

#### Concrete example

```python
def initialize_all() -> Morphism:
    result = identity(0)
    for channel, width in [(ttl0, 1), (ttl1, 2)]:
        if width > 0:
            result = result >> initialize_channel(channel, width)
    return result
```

The aggregate is Compile-known, ordered, homogeneous, and destructured with one
fixed pattern. Specialization preserves its element order.

#### Acceptance criteria

- [ ] Ordered homogeneous tuple/list values specialize in fixed order.
- [ ] Statically evaluated list comprehensions use the same iteration budget;
      each entered generator-clause iteration is charged.
- [ ] Comprehension filters use CompileTime selected-path semantics.
- [ ] Fixed-arity tuple/list patterns containing only local names destructure
      elements and produce clear arity/type diagnostics.
- [ ] Sets, mappings, generator expressions, heterogeneous aggregates, and
      host-order-dependent values fail with source provenance.
- [ ] Nested aggregate/range loops share the request-level counters.
- [ ] Specialized output matches an equivalent manually written Serial
      Morphism and contains no Hardware control node.

#### Blocked by

- #48

## Published tracker metadata

- Title: `Make ordinary Python control CompileTime`
- Labels: `enhancement`
- Removed: `ready-for-agent`
- State: open tracking issue
- Hardware implementation issues: none in the current scope
