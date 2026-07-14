# Prototype verdict

Question: should a structure-preserving CatSeq Morphism use nested Python objects
or an integer-indexed arena, and what performance tradeoffs appear in a minimal
serial workload?

Benchmark verdict from the local run on 2026-07-12:

- Arena construction scaled linearly: 0.442 ms at 1,000 atoms, 1.259 ms at
  3,000, and 4.137 ms at 10,000.
- Flat tuple concatenation plus a full summary rescan scaled quadratically:
  6.314 ms, 56.355 ms, and 631.211 ms at the same sizes. At 10,000 atoms the
  arena was about 153x faster to construct.
- The object DAG also scaled linearly (5.478 ms at 10,000 atoms). The arena was
  about 1.32x faster to construct and retained 515 KiB instead of 1,717 KiB,
  about 70% less memory.
- Dense-array arena traversal was slower than direct object traversal: 3.913 ms
  versus 3.455 ms at 10,000 atoms, and 11.460 ms versus 6.168 ms at 100,000.
  This is the principal measured cost of the arena representation in pure
  Python.
- Recursive traversal of the 100,000-atom left-deep object DAG raised
  `RecursionError`. Explicit-stack traversal completed for both representations,
  confirming that stack safety is an algorithm property rather than an arena-only
  property.
- On the synthetic 30,000-atom dependency model, value-only rebinding touched
  100 calls and no timestamps, measuring 32.8 us versus 9.60 ms for a full pass
  (293x). A timing change in the middle touched 15,000 timestamps and measured
  0.781 ms versus 9.62 ms (12.3x). A timing change in the final 1% touched 300
  timestamps and measured 15.5 us versus 9.68 ms (627x).

Decision supported by this prototype: an integer-indexed arena is viable and is
preferable to nested objects when CatSeq needs stable NodeIds, compact retained
structure, topological passes, and explicit-stack traversal. It should not be
selected on traversal speed alone: Python object traversal was faster. The
production design should keep hot per-node summaries in dense arrays and avoid
materializing all atoms when an incremental query can remain at subtree/epoch
granularity.

Scope warning: this prototype does not model multiple channels, parallel padding,
state propagation, board cohorts, epoch scheduling, OASM cost analysis, or final
assembly. Any production decision must retain the full CatSeq equivalence gates.
The large incremental speedups are synthetic upper bounds, not predictions for
the current end-to-end Rydberg compiler.

## Real rb1-next Rydberg offline compilation

The actual `rb1-next/experiments/computing/rydberg_transfer.py` Morphism was
measured for seven post-warmup repetitions at `pulse_time_us=0.35` and
`frequency_mhz=484.75`. The script used `assembler(None, nodes)`, did not open a
`BaseExp` context, and never called `seq.run()`.

Artifact shape was stable on every repetition:

- 52 lanes and 3,016 lane operations;
- 571 compiler events and 745 final OASM calls;
- duration 283,075,580 cycles;
- 10 active assembly boards;
- normalized calls SHA-256
  `efd651ff0a297f53dec7e32819882f574acb000f29c30c5d64705ea189ca606e`;
- integer assembly SHA-256
  `98a5a73dd2068cc45c334c1eb7f91b326d698ab602974d9020964f10cb905415`.

Seven-sample medians:

| Stage | Median |
| --- | ---: |
| Morphism build | 48.173 ms |
| `contains_expr` | 18.785 ms |
| extract + translate | 1.860 ms |
| costs + epochs | 16.881 ms |
| schedule + optimize | 2.208 ms |
| validate | 1.268 ms |
| generate calls | 0.678 ms |
| CatSeq compiler total | 41.696 ms |
| in-memory OASM assembly | 44.204 ms |
| build + compile + assembly | 134.398 ms |

This confirms that a structure-preserving implementation has two material
targets on the real workload: eliminate the 48 ms eager Morphism construction
cost and reuse enough bound/compiler/assembly work to avoid paying the remaining
roughly 86 ms for every scan point. The current benchmark is a baseline; it does
not claim arena speedup until the arena representation is integrated behind the
real composition operators.

## Real Rydberg arena-backed Morphism construction

A process-local throwaway runtime replaced `Morphism` construction and the
existing `>>`, `|`, `@`, and deferred dictionary application implementations
with an append-only arena. The experiment source and timing-composition calls
were unchanged. Provenance breadcrumbs were stored on composition nodes and
applied when a legacy Lane view was requested. No final CatSeq compile was run.

The arena result matched the baseline on duration, lane count, operation count,
and a semantic hash excluding debug identity:

- 283,075,580 cycles;
- 52 lanes;
- 3,016 operations;
- semantic SHA-256
  `b7812e0d956a88e4b75576f14c7441c57f8afdfcb50f17a66c7bb85d729da9d2`.

Seven-sample medians from the final provenance-preserving version:

| Measurement | Baseline | Arena |
| --- | ---: | ---: |
| Build / lazy build | 47.130 ms | 50.371 ms |
| Build plus final Lane materialization | 47.130 ms | 51.860 ms |
| Peak memory during build | 4,037 KiB | 7,148 KiB |
| Peak after final materialization | 4,037 KiB | 7,301 KiB |

The arena lazy build was about 6.9% slower; build plus the final compatibility
view was about 10.0% slower. Lazy peak memory was about 77% higher.

The diagnostic state explains why a storage-only replacement loses:

- 2,500 arena nodes: 1,748 leaves, 458 auto-serial, 211 parallel, and 83
  deferred concat nodes;
- existing construction code requested a Lane view 1,988 times before the final
  result was inspected;
- 745 of the 752 composition nodes had already been materialized during
  `build_sequence`; final materialization evaluated only seven more;
- 292 materialized compatibility roots remained cached before final inspection.

Verdict: replacing the Morphism container with an arena while preserving current
internal `.lanes` state inspection is not a performance win on real Rydberg
construction. A production arena design must also replace internal Lane reads
with O(1) DAG summaries for channels, duration, initial/end/effective states, and
deferred-operation input states. Without that accompanying internal rewrite, the
arena keeps both the DAG and almost the entire sequence of materialized Lane
views, increasing both time and memory.

## Arena state-query follow-up on real Rydberg

The arena prototype was then changed so `get_end_state`, `get_start_state`,
MorphismDef application, channel enumeration, and deferred base-state lookup use
memoized `(NodeId, Channel)` `ChannelStateSummary` queries. The query carries raw
initial/end state, effective initial/end state, and whether a non-identity
operation exists. It evaluates with an explicit work stack and never materializes
the base Lane.

The final 15-sample run remained semantically identical to the baseline:

- duration 283,075,580 cycles;
- 52 lanes and 3,016 operations after compatibility materialization;
- semantic SHA-256
  `b7812e0d956a88e4b75576f14c7441c57f8afdfcb50f17a66c7bb85d729da9d2`.

| Measurement | Baseline | Arena + state query |
| --- | ---: | ---: |
| Build / lazy DAG result | 47.417 ms | 42.275 ms |
| Build plus final Lane materialization | 47.417 ms | 56.148 ms |
| Peak memory during build | 4,006 KiB | 6,470 KiB |
| Peak after final Lane materialization | 4,006 KiB | 7,345 KiB |

The state-query arena reduced the build-to-DAG time by about 10.8%. It still used
about 61.5% more peak memory. Converting the result back into legacy Lanes erased
the time win and made the total about 18.4% slower, so the later compiler must
consume the DAG directly.

Diagnostic change versus the storage-only arena:

- composition nodes materialized before final inspection fell from 745 to 322;
- 945 state-query requests produced 4,478 cached `(node, channel)` results;
- the returned graph contained 2,417 nodes: 1,665 leaves and 752 composition
  nodes;
- final Lane materialization evaluated another 351 composition nodes;
- remaining materialization comes from leaf-local RWG helpers and nested
  construction-time compilation paths that still consume Lane views.

Verdict: direct state queries are sufficient to turn the real Rydberg arena build
from a regression into a modest construction win. The result also confirms the
architectural condition: the DAG must remain the compiler input. If a Lane view
is required before compilation, the arena is slower overall and consumes more
memory than the current representation.

## Why the state-query arena still takes about 42 ms

Separate 15-iteration cProfile runs were captured for baseline and arena builds.
cProfile adds substantial absolute overhead, so cumulative times below identify
relative hot paths and must not be summed as wall-clock percentages.

Arena-specific findings:

- `query_state` ran 945 times per build and evaluated/cached 4,478 node/channel
  results. It accumulated 0.507 s over 15 profiled builds, about one quarter of
  profiled build time.
- Those queries still key Python dictionaries and frozensets with full `Channel`
  dataclass objects. The profile observed 548,145 generated dataclass hash calls
  and 1,686,105 built-in hash calls over 15 builds. A production arena should
  assign dense integer `ChannelId`s and use array-indexed state tables/bitsets.
- Remaining Lane compatibility access called `materialize` 1,813 times per build
  and accumulated 0.204 s over 15 builds. Most requests are cheap leaves, but 322
  composition nodes are still materialized before the final result.
- The arena still creates 2,417 Morphism root handles/nodes per build. Its
  constructor accumulated 0.146 s over the profile.

Representation-independent or partially reduced costs:

- Rydberg construction performs seven nested `compile_to_oasm_calls` operations
  per build through state preparation/repeat-morphism helpers. They accumulated
  0.149 s over 15 arena builds; `repeat_morphism` accumulated 0.202 s.
- Two `numpy.load` calls occur per build in shuttling/addressing setup and
  accumulated 0.155 s, including 0.092 s in file seeks.
- `capture_callsite` ran 2,776 times per arena build and accumulated 0.182 s.
  Composition breadcrumb creation accumulated another 0.108 s.
- Even after state-query migration, 3,584 legacy `Lane.__post_init__` calls per
  build remain in leaves, deferred suffixes, and nested compile compatibility
  paths. Arena reduced this from roughly 7,822 per baseline build, but did not
  eliminate it.

The remaining time therefore is not arena append cost. It is dominated by a
Python-object implementation of the state-query layer plus work that
`build_sequence` performs outside Morphism storage: nested compilation, file
loading, provenance capture, atomic/state construction, and compatibility Lane
materialization.

## Optimized arena state and atomic leaves

The throwaway runtime was optimized without changing the experiment or CatSeq's
public timing-composition API:

- channels are assigned dense arena-local integer IDs and node channel sets are
  represented as integer bitmasks;
- state-query caches are indexed first by integer `NodeId`, then integer
  `ChannelId`, avoiding full `Channel` dataclass hashing in the hot traversal;
- `from_atomic()` writes the `AtomicMorphism` directly into the arena instead of
  eagerly wrapping it in a one-operation `Lane` and legacy `Morphism`;
- a legacy view of an atomic leaf is created only when old code requests
  `.lanes`, then cached for subsequent compatibility reads;
- immutable provenance `DebugFrame` values are reused by source callsite.

The final 15-sample real Rydberg run produced the same 52 lanes, 3,016
operations, 283,075,580-cycle duration, and semantic SHA-256
`b7812e0d956a88e4b75576f14c7441c57f8afdfcb50f17a66c7bb85d729da9d2`.

| Measurement | Baseline | Optimized arena |
| --- | ---: | ---: |
| Build / lazy DAG result | 47.542 ms | 39.693 ms |
| Build plus final Lane materialization | 47.542 ms | 54.674 ms |
| Peak memory during build | 4,005 KiB | 5,040 KiB |
| Peak after final Lane materialization | 4,005 KiB | 5,914 KiB |

The optimized lazy build is 16.5% faster and clears the 15% prototype gate in
ADR 0002. Lazy peak memory is still 25.8% higher. Forcing a complete Lane view
is 15.0% slower than the baseline and uses 47.7% more peak memory, so the result
still supports a DAG-native compiler boundary rather than a DAG-to-Lane adapter
before compilation.

The final graph has 2,417 nodes: 1,145 direct atomic leaves, 520 legacy/batch
leaves, 458 auto-serial nodes, 211 parallel nodes, and 83 deferred concat nodes.
Before final inspection, 322 composition nodes had been materialized by legacy
compatibility paths. There were 848 root state requests and 4,478 evaluated
node/channel summaries.

The last profile shows that the largest remaining costs are no longer arena
append operations:

- old code still requests `.lanes` 1,813 times per build, retaining 931 cached
  compatibility roots and materializing 322 composition nodes;
- `MorphismDef._execute_on_channel` still flattens generator pieces locally;
- seven nested `compile_to_oasm_calls` invocations remain in construction-time
  state-preparation helpers;
- addressing and shuttling each call `numpy.load` on every build;
- atomic debug annotation still copies dataclasses when applying provenance.

An attempted rewrite of every deferred suffix as a chain of binary parallel DAG
nodes was rejected by measurement. It increased the graph from 2,417 to 3,566
nodes, state-query evaluations from 4,478 to 12,031, and the three-sample lazy
build to 44.929 ms. A production arena should therefore have a native batch or
n-ary parallel node for multi-channel suffixes instead of mechanically lowering
them to a deep binary tree.

Prototype caveat: the runtime maps canonical `Channel` objects to dense IDs by
Python object identity. Production should assign stable apparatus-scoped
`ChannelId` values explicitly and must validate provenance, state mismatch, and
symbolic-duration behavior with the full CatSeq equivalence suite.

## Isolating arena storage from `build_sequence`

The approximately 39.7 ms number above is the time for the complete RB1
`build_sequence(params)` call to produce a lazy DAG. It is not the time spent
appending nodes to the arena. To remove that ambiguity,
`isolate_arena_cost.py` captures the exact 2,417-node stream from the real
Rydberg build and replays its leaf payloads, edges, channel summaries, durations,
and NodeId order into a fresh arena without rerunning domain factories.

The 501-repetition median was **0.941 ms**, below the explicit 1 ms limit. This
confirms that arena storage is already in the expected performance class. The
remaining roughly 38.8 ms belongs to executing the Python builder and legacy
compatibility behavior around the arena.

Consequently, further container micro-optimization cannot make a scan-point
build take 1 ms. Reaching that target requires changing the execution model:

1. execute the Python sequence builder once to create a parameterized arena
   template;
2. store scan inputs as `ParamId` references in affected atomic payloads and
   duration summaries;
3. build a reverse dependency index from `ParamId` to atomic NodeIds and derived
   timing/state/compiler nodes;
4. represent each scan point as a small binding/version overlay on the shared
   template rather than calling `build_sequence` again;
5. make state queries and the compiler consume the template plus binding overlay
   directly, without constructing compatibility Lanes.

At that seam, “Morphism construction per scan point” becomes an environment
update and invalidation operation, for which sub-millisecond performance is a
realistic target. The one-time template construction may remain tens of
milliseconds without affecting scan throughput.

## Fully lazy deferred/state construction result

The prototype was then changed to allow semantic state errors at compile time,
as explicitly accepted for this experiment. Construction now records four
state- or compiler-dependent node types without expanding them:

- `DEFERRED_CHANNEL`: a `MorphismDef`, channel, and optional explicit start
  state;
- `DEFERRED_APPLY`: an operation mapping applied to the end states of a base
  root;
- `DEFERRED_BATCH`: a batch whose start states depend on another root, used by a
  lazy `get_end_state` view plus the unchanged RB1 `dict_to_morphism` call shape;
- `REPEAT`: a hardware-loop node that defers its nested CatSeq/OASM compilation.

Unknown durations propagate through construction summaries. Requesting a
concrete duration, state value, Lane view, or compilation result triggers the
relevant node. The normal `>>`, `|`, `@`, MorphismDef, `get_end_state`, and RB1
service call sites were unchanged.

Final 15-sample Rydberg result:

| Measurement | Baseline | Fully lazy arena |
| --- | ---: | ---: |
| Full `build_sequence` to result | 47.467 ms | 13.611 ms |
| Build plus compatibility Lane materialization | 47.467 ms | 50.799 ms |
| Peak memory during build | 4,005 KiB | 2,750 KiB |
| Peak after compatibility materialization | 4,005 KiB | 5,615 KiB |

The lazy build is 71.3% faster and uses 31.3% less peak memory. Construction
performs zero state queries, zero materialization requests, and zero composition
materializations. It returns 778 nodes: 163 auto-serial, 182 parallel, 237
deferred-channel, 83 deferred-apply, six deferred-batch, one repeat, and 106
legacy/configuration leaves. Atomic operations inside deferred definitions are
not created until the unified pass.

The exact 778-node storage stream replays in **0.295 ms** median over 501 runs.
Most of the remaining one-time 13.6 ms template-builder cost is outside arena
storage; the final profile is led by two calibration `numpy.load` calls in
addressing/shuttling initialization, followed by Python service/factory and
provenance construction.

Compatibility materialization expands the graph to 2,529 nodes and takes about
37.2 ms. The result remains identical to the baseline: 52 lanes, 3,016
operations, 283,075,580 cycles, and semantic SHA-256
`b7812e0d956a88e4b75576f14c7441c57f8afdfcb50f17a66c7bb85d729da9d2`.
This reinforces that production compilation must lower the deferred DAG
directly instead of first creating legacy Lanes.

Compile-time error timing was also verified with an invalid strict composition.
`ttl_on(OFF) @ ttl_on(OFF)` builds three nodes with zero materialization and then
raises on materialization with the mismatch plus the arena `NodeId`, kind,
children, and both source callsites. Retaining the DAG therefore improves error
localization even though validation moves later.

## Updating a real Rydberg scan parameter

`real_rydberg_scan_binding.py` builds the real sequence once with
`Expr.var("pulse_time_us")` instead of a concrete pulse duration. The resulting
778-node arena is treated as an immutable template. A scan point calls
`template.fork({"pulse_time_us": value})`, which copies only the compact topology
arrays and state-cache shells while sharing immutable payload objects.

The prototype inspects deferred-definition closures and expression payloads to
build a transitive `ParamId -> NodeId` reverse index. For `pulse_time_us`, only 13
of the 778 Morphism nodes are dirty:

```text
725, 727, 728, 729, 731, 733, 734, 736, 737, 739, 759, 761, 777
```

Over 501 repetitions, binding/fork medians were 0.00945 ms at 0.35 us and
0.00940 ms at 0.55 us. Evaluating both forks left the template unchanged.

Both bound results matched independent concrete Rydberg builds exactly:

| Pulse time | Duration | Operations | Semantic match |
| ---: | ---: | ---: | --- |
| 0.35 us | 283,075,580 cycles | 3,016 | yes |
| 0.55 us | 283,075,630 cycles | 3,016 | yes |

The 50-cycle difference is exactly 0.20 us at 250 MHz. This validates the
template-plus-binding update model: changing a scan parameter does not rewrite
the DAG and costs about 10 microseconds in this Python prototype.

The compatibility evaluation still takes roughly 97-98 ms because it resolves
expressions by rebuilding all legacy atomic dataclasses and Lanes. That is not an
incremental compiler result. A DAG-native compiler should keep per-NodeId bound
artifacts, invalidate the 13 Morphism nodes above, then add timing-successor and
epoch/board dependency edges for downstream timestamp and assembly invalidation.
