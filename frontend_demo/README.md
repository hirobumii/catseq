# CatSeq frontend demos

This directory is the reviewable source-language boundary for CatSeq's next
frontend.  It plays the same role as `nac3standalone/demo`: the programs are
kept outside `tests/`, each file is independently readable, and the corpus is
created before the corresponding compiler feature.

This is not a second Python project and it is not end-user documentation.  It
is part of the CatSeq repository.  The programs deliberately include proposed
APIs that are not implemented yet, so a design can be changed by editing a
small program before compiler internals make that choice expensive.

## Responsibility boundary

The source always describes one logical timed/control program.  It does not
emit per-board instruction lists and does not infer timing from Python, Wasm,
or OASM call order.

| Concern | Source/frontend | Target lowering |
| --- | --- | --- |
| several channels | compose one Morphism with `>>`, `|`, or channel binding | bind logical channels and select instructions |
| several boards | retain unified anchors, causality, resources, and Epochs | partition board fragments and apply board-local optimizations |
| exact cross-board timing | declare one exact Morphism or `control.fixed_end` Control | schedule transport/dispatch and prove deadlines |
| dynamic cross-board completion | explicitly request `control.epoch_join(sync_contract)` | encode rendezvous, timeout, and new-origin establishment |
| RWG preparation and scalar compute | write ordinary data dependencies | place schedulable work by release, deadline, WCET, and resources |

Consequently, `morphism_multiboard_parallel.py` contains no manually split
`board_a_program`/`board_b_program`.  Conversely,
`control_multiboard_epoch_join.py` does name the synchronization policy because
silently inserting a runtime barrier would change program semantics.

## Language boundary represented by the programs

### Kernel Functions, Compute, and native Python control

`@kernel` marks compiler-only entry and topology-construction functions.
Direct callees are statically resolved.  One pure Compute semantic domain has
two source forms:

- a reusable named ComputeFunction declared with `@compute`; and
- an anonymous ComputeRegion completely outlined from inline pure Device
  scalar source inside `@kernel`.

Straight-line arithmetic, supported native `if/elif`, and statically bounded
scalar loops may appear inline, but no executable Device CFG/SSA remains in
Kernel IR.  CatSeq records opaque typed Compute calls and schedulable work;
the pinned CatSeq NAC3 fork owns Compute body typing, CFG/SSA, and later
LLVM/Wasm lowering.  Neither Compute source form advances the logical cursor.

ComputeRegion and ComputeFunction bodies have no floating-point types or
instructions. Realtime numeric code therefore uses integers, target nominal
words, or an explicit fixed-point type. Source `float` may exist only outside
Compute, and only when the frontend resolves it to an accepted non-float
Compile/Link value before it enters a ComputeRegion, ComputeFunction call, or
Compute ABI. An internal `float @ Device` fact or Device-time float operation is
rejected. Availability never creates a second Python type family.

Native Python control may affect Morphism topology only when its controlling
value is Compile-known.  A Link/Device value that selects topology must use an
explicit Control combinator.  Closures, first-class Kernel Functions, indirect
dispatch, host helpers, and runtime recursion fail closed.

Python annotations describe ordinary semantic types, not availability wrappers:

```python
@compute
def classify(count: int, threshold: int) -> int:
    ...
```

Availability is a compiler fact propagated from producers and bindings, not a
second source type. If `count` comes from measurement and `threshold` is a
default entry argument, the HIR facts are `count: int @ Device`, `threshold:
int @ Compile`, and `result: int @ Device`. The same ComputeFunction called with
two constants has a Compile result. Link fixtures declare entry parameters
through `LINK-BINDING` contract metadata while the Python annotation remains
`bool`, `int`, or another ordinary base type.

### Typed Source HIR

`source_hir_loop_free.py` and `source_hir_compute_reference.py` use the real
`BaseExp.build_sequence(ExpParams)` entry shape.  They define the first #52
source-analysis contracts: exact registered-object authority, entry-rooted
reachability, admitted request reads, typed call/read edges, and an opaque
Compute reference.  Successful HIR is Python-free and target-independent;
failure publishes no partial report.  ValueExpr, Morphism/Control graphs,
DeviceValue SSA, target planning, and backend artifacts remain downstream.

### Morphism

Morphism remains the composable timed event/resource algebra.  It can span
several channels and boards.  `identity(0)` is the zero-duration composition
identity in the current spelling; nonzero `identity(duration)` moves the
logical cursor used to place rigid events, including negative rewind.  It is
not controller blocking work.

Compile-known invariant repetition remains MorphismPower.  Whether it becomes
a hardware loop or an unrolled fragment is a target-lowering decision.  A
Device-controlled temporal loop is Control instead.

### Device values and Control

Structured control belongs to the public `catseq.control` namespace.  Source
programs import the constructor namespace and the annotation separately:

```python
from catseq import control
from catseq.control import Control
```

`control.branch`, `control.switch`, `control.loop`, `control.fixed_end`, and the
other structured-control constructors live there.  `catseq.hardware` remains
the namespace for device operations, hardware resources, and synchronization
contracts; it does not contain a second `hardware.control` surface.

The public source annotation `Control` is deliberately non-generic.  Its result
parameter belongs to canonical compiler IR, where every Kernel Function can be
viewed uniformly as `A -> Control<B>`.  Value-bearing source functions expose a
dependent temporal/value pair instead of spelling that internal generic:

| Source return annotation | Normalized internal result |
| --- | --- |
| `int` | `Control<int>` with an empty temporal projection |
| `Morphism` | `Control<Unit>` after compiler-owned Lift |
| `Control` | `Control<Unit>` |
| `tuple[Control, int]` | `Control<int>` |
| `tuple[Control, LoopResult]` | `Control<LoopResult>` |

Consequently, source code never writes `Control[None]`, `Control[int]`, or any
other `Control[...]`.  `LoopResult` is an ordinary public result record; the
generic `Control<LoopResult>` carrier remains internal.

A measurement returns a source-level dependent pair:

```python
capture, count = detector0.measure(10 * us)
```

`capture` is an ordinary composable Morphism. `count` is a typed Device SSA
value whose producer is that Morphism and which carries dominance, Epoch,
readiness, and transport facts. The tuple is erased before CanonicalProgram;
using `count` without placing `capture` on a dominating path is rejected.

Ordinary Python `if/elif` may transform that result as a scalar value.  Explicit
`control.branch`/`control.switch` selects statically present Morphism/Control
regions.  `control.fixed_end(D)` covers the whole region—predicate readiness, compute,
transport, dispatch, selected arm, and padding.  An arm-local cursor Wait is not
an alternative spelling for that join.

Mixed `M >> C`, `C >> M`, and `C >> C` composition produces Control through a
compiler-owned Lift; source never constructs canonical Lift nodes.  Ordinary
`|` involving Control is accepted only for `SameEpochExactNormal` operands.

### DataCache-driven realtime kernels

A bounded `DataCacheView[T]` is an ordinary source type for board-local data;
it is not an availability wrapper and it does not expose cache addresses or
RTMQ registers.  A module-level `hardware.data_cache.store(...)` declaration
binds initial data and a maximum capacity without adding a timed event to the
program.  Replacing the contents within that declared contract must not change
canonical Control topology.

`realtime_rb_datacache.py` stores one already-decomposed RB primitive-gate
sequence and passes its view to a reusable Kernel Function.  The function uses
a bounded `control.loop` to read integer gate codes and an exhaustive static
`control.switch` to select RWG Morphism arms.  Every arm uses real RWG
`set_state`/`hold` operations and returns the channel to an explicit idle
waveform.  Floating-point waveform descriptions are Compile-known records and
must be quantized before Device execution; DataCache reads and Device dispatch
remain integer work.

The frontend records the typed view, capacity requirement, reads, value
dependencies, static gate alternatives, logical RWG resource, and timing
contracts in CanonicalProgram.  Physical cache placement, upload transport,
load instructions, hardware-loop selection, and RWG instruction encoding are
backend concerns and are deliberately absent from the example.

### Epochs

When runtime completion cannot inherit the old absolute timeline, source must
use `control.epoch_join(sync_contract)`.  Participating boards are inferred from
logical resource support, but timeout/failure and synchronization authority are
semantic choices and therefore explicit.  Timestamps on opposite sides of the
join belong to different Epochs.

## Accepted design programs

| Area | Programs | Boundary shown |
| --- | --- | --- |
| Typed Source HIR | `source_hir_loop_free.py`, `source_hir_compute_reference.py` | exact BaseExp root, reachable definitions and reads, opaque Compute reference |
| public Kernel entry | `kernel_identity.py` | compiler-only body and channel-bound result |
| Kernel calls | `kernel_calls_kernel.py` | Compile-known scalar and Morphism-producing direct callees |
| Compute | `device_scalar_if_elif.py`, `device_scalar_early_return.py`, `device_scalar_bounded_while.py`, `device_pure_compute_loop.py`, `device_mandelbrot.py` | explicit ComputeFunctions, automatic ComputeRegions, and temporal Control separation |
| Compile topology | `compile_known_if.py`, `compile_known_if_false.py`, `compile_known_for_range.py` | selected finite topology, no runtime Choice |
| Morphism algebra | `morphism_multichannel_parallel.py`, `morphism_cursor_anchors.py`, `morphism_resource_binding_linear_ramp.py`, `morphism_power.py` | parallel resources, cursor/frontier, resource-indexed Morphisms, power |
| static multi-board | `morphism_multiboard_parallel.py` | unified source and automatic board partitioning |
| Device SSA | `device_measurement_feedback.py`, `control_value_output.py` | measurement, readiness, predicate, continuation, value-bearing Control result |
| Branch/Switch | `device_measurement_feedback.py`, `control_switch.py` | explicit finite runtime topology and whole-region join |
| mixed composition | `control_lift_and_serial.py` | compiler-owned Lift and maximal Morphism islands |
| exact Control parallel | `control_parallel_exact.py` | narrow legal ordinary `|` subset |
| runtime loop | `control_bounded_loop.py` | static body, carry, bound, exhaustion, exact envelope, returned carry result |
| DataCache RB | `realtime_rb_datacache.py` | bounded cache view, reusable realtime gate dispatcher, real RWG Morphisms |
| Link guard | `link_known_choice.py` | canonical arms retained, immutable Link projection |
| cross-board feedback | `control_multiboard_fixed_end.py` | automatic predicate transport within one Epoch |
| cross-board rendezvous | `control_multiboard_epoch_join.py` | explicit new Epoch and inferred participants |
| schedulable work | `schedulable_work_and_anchors.py` | RWG load/compute placement independent of rigid anchors |

## Rejected boundary programs

| Area | Programs | Rejected behavior |
| --- | --- | --- |
| call graph | `reject_unimplemented_host_rpc.py`, `reject_indirect_kernel_call.py`, `reject_device_function_dispatch.py`, `reject_kernel_closure.py`, `reject_recursive_kernel.py` | host/dynamic/recursive call authority |
| topology/value type | `reject_device_topology_if.py`, `reject_ignored_morphism_result.py`, `reject_temporal_early_return.py`, `reject_device_float.py`, `reject_inline_device_float.py` | implicit `Phi<Morphism>`, lost topology, abrupt temporal return, unsupported realtime float |
| resources | `reject_same_channel_parallel.py` | overlapping exclusive channel claims |
| Boundary contracts | `reject_linear_ramp_without_active_snapshot.py` | initialization does not provide the active snapshot required by a ramp |
| readiness | `reject_use_before_ready.py` | source construction order used instead of temporal dominance |
| joins | `reject_branch_arm_wait_as_join.py`, `reject_dynamic_control_parallel.py`, `reject_implicit_epoch_join.py`, `reject_continuation_after_terminal.py` | hidden completion/barrier/Epoch or absent continuation |
| repetition | `reject_unbounded_control_loop.py`, `reject_device_morphism_power.py` | unbounded runtime topology or Device MorphismPower |


## Contract header and implementation status

Every file starts with a compact expectation block:

```python
# CATSEQ-DEMO: 1
# STATUS: proposed
# ISSUE: #58
# ENTRY: sequence
# EXPECT: accept
# LINK-BINDING: optional_link_parameter
# CONTRACT: control.fixed_end covers the complete Choice region.
```

`proposed` means the code and its semantic claims are ready for design review;
it does **not** claim compiler support.  Normal checking validates headers and
Python syntax without importing a module.  Strict checking remains red.

`required` is used only after the owning issue is selected and a public
registered-source analysis adapter can check the declared result.  That adapter
does not exist during the #52 migration, so required contracts fail rather than
falling back to the removed compiler.  Accepted semantic programs must not be
promoted until #33 exposes a public target-independent CanonicalProgram
serialization/hash that the runner can compare.  A successful source check
alone is intentionally not accepted as proof of topology, normalization,
resource, or Epoch semantics.

The runner does not import demos or call a `@kernel` body.  The future public
actual-object analysis route may import a module using normal Python semantics
as specified by #53; demo module top level is therefore limited to declarations
and inert resource construction.

## Commands

Use the existing locked project environment and the persistent uv cache.  Do
not execute a demo source as host Python.

```console
uv run python frontend_demo/check_demo.py \
  frontend_demo/src/control_multiboard_fixed_end.py
uv run python frontend_demo/check_demos.py
uv run python frontend_demo/check_demos.py --strict
```

The last command is intentionally red while contracts remain proposed. A
required contract also remains red until the public registered-source analysis
adapter is implemented; the runner has no legacy compiler fallback.

Do not use `--offline` or `uv run --with`.  Whole-directory mypy is also
expected to fail until the proposed Control, measurement, scheduling, and
rendezvous surfaces exist; type-check the two runner files independently
during this design stage.

## Source spellings still intentionally open for review

The sequencing value spelling is settled: user source has one `Morphism` type,
and reusable definitions use `@morphism`. The remaining provisional names may
still change:

- the exact typed syntax for `loop_value`, carry edges, and exhaustion;
- the concrete spelling and exact constant constructors for `fixed32[F]`;
- the concrete Link-value declaration spelling;
- the prepared-RWG handle returned by schedulable `rwg.load`;
- the exact `DataCacheView` and `hardware.data_cache.store` binding spellings;
- the synchronization-contract constructors under `hardware.sync`.

Those choices are visible here precisely so they can be decided before
implementation.  The invariant decisions—static topology, explicit temporal
joins, Morphism composability, Device SSA readiness, and automatic target board
partitioning—must remain unchanged when names are revised.
