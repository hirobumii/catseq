# CatSeq experiment-control clean-port plan

Document class: active migration plan

Status: CatSeq phases 1-5, rb1-next migration, and the TTL tracer bullet are
verified; CatSeq publication and full RB1 hardware acceptance remain

Target namespace: `catseq.experiment`

Source baseline: `rb1-next` at
`ce878065fdaf5235315686907728ce423925bd83`

CatSeq baseline: `61a83441c228b8b21ca957dc0ba2f624d403a408`

This document is the execution checklist for moving the generic experiment
control now implemented in `rb1-next/rb1system/abstract` into CatSeq. A phase is
complete only after its gate passes. Checkboxes record verified behavior, not
code that merely exists.

## Goal

Make `catseq.experiment` the reusable host-side experiment framework above the
existing CatSeq compiler and runtime:

```text
RB1 experiments and deployment adapters
                  |
                  v
          catseq.experiment
       BaseExp and experiment concepts
                  |
                  v
      CatSeq Compiler and Runtime
```

An experiment subclass describes its sequence, scan, devices, and analyzers.
`BaseExp` owns the lifecycle of one complete execution and hides traversal,
dependency ordering, point execution, publication, persistence, and cleanup.
RB1 supplies target-specific collaborators; CatSeq does not discover or build
them.

## Fixed decisions

1. Generic experiment control lives under the `catseq.experiment` namespace,
   split into focused public modules. The package root is not a facade that
   re-exports every experiment type.
2. One `BaseExp` instance represents one complete experiment execution. There
   is no additional `ExperimentRun` domain object.
3. `BaseExp` owns orchestration, not platform construction. The compiler,
   runtime, devices, run control, panel publisher, and H5 writer are supplied by
   the concrete experiment or its runner.
4. The port preserves experiment behavior, not the inheritance and persistence
   coupling of `SavableABDC`.
5. `ExpParams` and `ScanPoint` remain immutable. Tensor coordinates are
   first-class scan metadata; flattened order records attempted execution order
   only.
6. One runner job owns the repeat and scan loop. Scan points are not expanded
   into separate scheduler jobs.
7. `ParaDict` records an attempted point before compilation or execution, so a
   failure is visible in the final record.
8. H5 is the only persistence format in this migration. It is a concrete
   CatSeq module, not the first adapter behind a speculative `ResultStore`
   interface.
9. Migrated consumers import the specific CatSeq experiment modules directly.
   There is no compatibility proxy or re-export package in
   `rb1system.abstract`; unmigrated experiments may temporarily keep using the
   old implementation until they are converted.
10. The OASM object model is not part of experiment control. `assembler`,
    `run_cfg`, `eth_intf`, `C_*`, `seq`, and `intf_usb` do not enter
    `catseq.experiment`.
11. Experiment orchestration is ordinary host Python and is never a CatSeq
   compiler input. At each attempted scan point, `BaseExp` passes only the
   bound `build_sequence` method and that point's immutable `ExpParams` to the
   compiler.
12. Consumer migration does not authorize deleting a legacy API merely because
   no current production file imports it. Removing an RB1 abstraction is a
   separate compatibility decision and requires an accepted semantic
   replacement; import counts are only migration evidence.
13. `BaseExp` owns a private one-point compilation lookahead. The first point
    compiles synchronously; while point N runs, point N+1 compiles in the
    background. Traversal waits for that compilation only when it reaches point
    N+1 and the result is not ready. A speculative compilation does not record
    a point as attempted in `ParaDict`.

These decisions supersede the older RB1/OASM-specific conclusions that
`BaseExp` should own `seq`, `intf_usb`, or an `execution_mode` switch. Runtime
selection is runner policy expressed by the supplied CatSeq runtime.

## Public module shape

`catseq.experiment` groups the experiment-control domain. Each cohesive module
owns its own public interface, and callers import from the module that defines
the concept:

```python
from catseq.experiment.analyzer import AnalyzerConfig, BaseAnalyzer
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.base_module import BaseModule, BaseService
from catseq.experiment.descartes import DescartesGenerator
from catseq.experiment.device import (
    BaseDevice,
    BaseDeviceIn,
    BaseDeviceInOut,
    BaseDeviceOut,
    DeviceList,
)
from catseq.experiment.indexer import Indexer
from catseq.experiment.panel import NullPanelPublisher, PanelPublisher, PanelUpdate
from catseq.experiment.para_dict import ParaDict
from catseq.experiment.params import ExpParam, ExpParams, ScanPoint
from catseq.experiment.result import BaseResult
from catseq.experiment.run_control import RunControl
```

The initial package layout is:

```text
catseq/experiment/
  __init__.py          namespace documentation; no bulk re-exports
  base_exp.py          complete experiment lifecycle
  base_module.py       BaseModule and BaseService sequence abstractions
  params.py            ExpParam, ExpParams, and ScanPoint
  descartes.py         repeat and tensor-scan traversal
  para_dict.py         append-only parameter history and queries
  run_control.py       cooperative pause and cancellation
  result.py            typed append-only result data
  device.py            device lifecycle and DeviceList aggregation
  analyzer.py          analyzer declarations and internal pipeline
  indexer.py           type-based dependency lookup
  panel.py             transport-independent panel contract
  h5.py                concrete H5 serialization and schema
```

These are public modules, not a collection of private files hidden behind one
large import surface. Each module keeps its exported names narrow and hides its
own helpers. `catseq.experiment.h5` remains explicit so importing the other
modules does not require H5 dependencies. Experiment-control names are not
duplicated in either `catseq.experiment.__init__` or the top-level `catseq`
package.

## Dependency rules

- `BaseExp` calls the public `Compiler` and the supplied runtime at the
  per-point boundary. Descartes traversal, device lifecycle, analysis,
  publication, persistence, and cleanup never enter the compiler.
- Experiment modules other than `h5` do not import `h5py` or NumPy. Only
  `catseq.experiment.h5` owns H5 encoding and its optional dependencies.
- No CatSeq experiment module imports `rb1system`, runner schemas, ScienceClaw,
  MQTT, RB1 configuration, or a hardware lock.
- RB1 concrete devices, analyzers, experiments, and runner adapters import the
  specific `catseq.experiment.*` modules they use; the dependency never points
  back into RB1.
- The compiler and runtime remain usable without importing experiment control.
  They do not classify or compile `BaseExp`, `BaseModule`, `BaseService`, or the
  experiment lifecycle. Reachable sequence-building methods remain ordinary
  CatSeq source definitions regardless of their host-side base classes.
- Do not add a public generic runtime or persistence protocol for this port.
  The current runtime and H5 writer are single concrete implementations. Tests
  can replace them at private seams inside the package.
- `PanelPublisher` remains a public protocol because Null and RB1 MQTT
  publishers are two real adapters at that seam.

## Planning baseline

The source audit on 2026-08-03 established these pre-migration checkpoints:

- The focused rb1-next framework suite passed 27 tests:

  ```text
  uv run pytest -q tests/test_params_and_para_dict.py \
    tests/test_descartes_generator.py \
    tests/test_baseexp_descartes_tracer.py \
    tests/test_reusable_analyzers.py
  ```

- CatSeq 0.3.2 checked the real
  `RydbergTransferExp.build_sequence` entry with 47 reachable definitions,
  4,175 HIR nodes, and zero diagnostics.
- The low-level Compiler/Ethernet Runtime TTL path produced the expected 500 ms
  plan and successful chassis-2 evidence on 2026-08-02. The current
  `hardware-tests/chassis2_ttl.py` is an interim RB1/OASM-based `BaseExp`
  version and is not final acceptance evidence.

## Source decomposition

| Current RB1 source | CatSeq destination | RB1 remainder |
| --- | --- | --- |
| `abstract/base_module.py` | `experiment.base_module`, retaining module initialization, channel state/style, and service composition while removing serialization | Concrete RB1 modules and services only |
| `abstract/params.py` | `experiment.params` | None |
| `abstract/descartes_generator.py` | `experiment.descartes` | None; H5 encoding moves separately |
| `abstract/para_dict.py` | `experiment.para_dict` | None; H5/NumPy encoding moves separately |
| `abstract/run_control.py` | `experiment.run_control` | Runner-owned `JobRunControl` adapter |
| `abstract/base_result.py` | `experiment.result` | None; H5 encoding moves separately |
| `abstract/base_device.py` | `experiment.device` | Concrete devices, factories, and process-local singleton policy |
| `abstract/base_analyzer.py` | `experiment.analyzer` | Concrete RB1 analyzers |
| `abstract/indexer.py` | `experiment.indexer` | None |
| `rb1system/panel.py` | `experiment.panel` | MQTT transport, topic naming, health, and ScienceClaw identity |
| `abstract/base_exp.py` | `experiment.base_exp`, rewritten over `Compiler.compile()` and runtime `run()` | Runtime/config construction, hardware lock, runner identity, and deployment policy |
| `abstract/util.py` | No destination; use explicit standard-library dataclasses and move H5 conversion into `experiment.h5` | Delete singleton, metaclass decoration, and `SavableABDC` aggregation |

This is a clean port. Files are not copied wholesale, and migrated consumers do
not use RB1 compatibility proxies. The legacy RB1 implementation may remain as
an independent API until a separate removal decision is made.

## Lifecycle contract

The public lifecycle operation is `BaseExp.run()`. An experiment subclass
provides `build_sequence(params)` and the narrow scan/analyzer hooks needed by
the existing model. The first attempted point has no prefetched result, so it
compiles synchronously. Each point then performs:

```text
record ScanPoint in ParaDict
  -> take its prefetched compilation, waiting if necessary
     (or compile synchronously for the first point)
  -> apply scan parameters to devices
  -> DeviceList.init_device()
  -> start Compiler.compile(build_sequence, next_point.params)
  -> Runtime.run(compiled_sequence)
  -> DeviceList.read()
  -> streaming analyzers
  -> optional panel publication
```

The compile of point N+1 overlaps `Runtime.run()` for point N. The immutable
next point is previewed internally by Descartes, but it is not appended to
`ParaDict` until normal traversal reaches it. Cancellation or a failure at the
current point can therefore leave one harmless speculative compilation without
turning that point into an attempted execution. A prefetched compile failure is
raised when traversal attempts that point.

The complete run surrounds that point loop with device startup, experiment
preparation, Descartes configuration, analyzer dependency resolution, final
analyzers, H5 persistence, and cleanup. Pause and cancellation are observed at
safe lifecycle checkpoints. Cleanup runs after both success and failure without
replacing the original failure.

Analyzer topological sorting, dependency injection, enabled/disabled handling,
streaming/final dispatch, and `PanelUpdate` collection are internal pipeline
behavior. They are tested through `BaseExp` and `BaseAnalyzer`, not published as
a second orchestration interface.

## Migration phases

### Phase 0: freeze observable behavior

- [x] Move or reproduce the focused RB1 framework tests as behavior tests for
  the new package interface.
- [x] Record the real Rydberg source-check baseline and the current TTL
  low-level compiler/runtime result.
- [x] Add a source check that prevents new imports from
  `rb1system.abstract` in migrated files.

Gate: the current focused RB1 suite remains green, and the CatSeq compiler
checks `RydbergTransferExp.build_sequence` with no diagnostics before any source
type moves.

### Phase 1: establish module, service, and parameter foundations

- [x] Add the public `catseq.experiment.base_module` and
  `catseq.experiment.params` modules; keep the package `__init__` free of bulk
  re-exports.
- [x] Clean-port `BaseModule`, `BaseService`, `ExpParam`, `ExpParams`, and
  `ScanPoint` without `SavableABDC` or H5 imports.
- [x] Keep these host abstractions out of compiler classification and compile
  only `build_sequence` plus its reachable sequence-building definitions.

Gate: module/service composition, immutability, mapping, and range-expansion
tests pass. A boundary test proves orchestration is not compiled, and the real
Rydberg `build_sequence` source still produces zero diagnostics.

### Phase 2: port scan traversal and run data

- [x] Clean-port `DescartesGenerator`, `ParaDict`, and `RunControl` as pure
  in-process modules.
- [x] Preserve repeat, tensor-scan, `final_exp`, streaming callback, and
  attempted-point ordering behavior.
- [x] Keep H5 conversion out of these classes.

Gate: tests cover nested repeat/scan traversal, tensor coordinates, final
analysis order, pause/cancel checkpoints, and a compile failure after the point
has already been recorded.

### Phase 3: port device, result, analyzer, indexer, and panel concepts

- [x] Clean-port result and device bases plus non-singleton `DeviceList`.
- [x] Build one internal analyzer pipeline for dependency sorting, dependency
  requests, streaming/final dispatch, and disabled analyzers.
- [x] Clean-port `Indexer`, `PanelUpdate`, `PanelPublisher`, and
  `NullPanelPublisher` without MQTT or ScienceClaw imports.

Gate: tests cover device lifecycle order, append-only results, analyzer
dependency cycles, missing dependencies, disabled analyzers, panel publication,
and two independent `DeviceList` instances in one process.

### Phase 4: centralize H5 persistence

- [x] Implement the concrete `catseq.experiment.h5` module.
- [x] Preserve the established groups: `static_para`, `dynamic_para`,
  `descartes`, `device`, `analyze`, and `debug`.
- [x] Move value conversion and dataset replacement rules out of experiment,
  device, result, analyzer, Descartes, and ParaDict classes.
- [x] Package `h5py` and NumPy behind a `catseq[h5]` optional dependency; all
  non-H5 experiment modules must still import without that extra.

Gate: one temporary-file integration test verifies the complete schema and can
read back tensor coordinates, attempted points, device results, analyzer
results, and failure diagnostics.

### Phase 5: implement BaseExp as the vertical slice

- [x] Implement one `BaseExp.run()` lifecycle over supplied collaborators.
- [x] Compile the first point synchronously, then compile one immutable point
  ahead while the current Compiled Sequence runs; wait when the next point is
  attempted before its compilation completes.
- [x] Prove the compiler receives only `build_sequence` and one point's
  `ExpParams`, never `run`, Descartes traversal, device, analyzer, or
  persistence code.
- [x] Keep speculative compilation distinct from attempted execution: only
  normal Descartes traversal appends the point to `ParaDict`.
- [x] Integrate Descartes, devices, analyzers, panel publication, H5, run
  control, and cleanup without exposing the internal pipeline.
- [x] Use simple fake devices, analyzers, publisher, and runtime in package
  tests; do not add public fake framework classes.

Gate: tracer experiments prove compilation/runtime overlap, waiting for an
unfinished next compilation, nested repeat/scan lookahead, compile failure,
runtime failure, cancellation, final analysis, H5 persistence, and cleanup
entirely through the public experiment interface.

### Phase 6: migrate rb1-next consumers directly

- [x] Add RB1 factories for CatSeq Compiler/Ethernet Runtime configuration,
  hardware locking, concrete devices, `JobRunControl`, MQTT panel publication,
  and run identity.
- [x] Migrate one experiment at a time to direct imports from the specific
  `catseq.experiment.*` modules it uses.
- [x] Keep unmigrated experiments on the old implementation; do not turn
  `rb1system.abstract` into a proxy.
- [x] Keep the legacy abstractions and panel contract intact after consumer
  migration. Any later removal requires its own accepted compatibility plan
  and is not inferred from a lack of imports.
- [ ] Update rb1-next from CatSeq 0.2.4/OASM-facing use to the CatSeq version
  containing `catseq.experiment`.

Gate: all migrated RB1 tests pass, no RB1 experiment imports CatSeq-private or
OASM execution symbols, and the real Rydberg source still checks with zero
diagnostics.

### Phase 7: hardware acceptance

- [x] Rewrite `hardware-tests/chassis2_ttl.py` as a self-contained,
  human-written `BaseExp` example importing `BaseExp` from
  `catseq.experiment.base_exp`, module/service bases from
  `catseq.experiment.base_module`, and compilation/runtime types from CatSeq.
- [x] Remove all OASM and `rb1system.abstract` imports from that file.
- [x] Verify the expected 500 ms call plan, successful chassis-2 RWG0 terminal
  evidence, and a readable H5 experiment record.
- [ ] Run the Rydberg experiment as the first full RB1 acceptance case after
  the TTL tracer bullet.

Gate: both the physical TTL run and the selected Rydberg run complete through
the new lifecycle with their execution evidence and H5 records retained.

## Removal checklist

The migration is not complete while any of these remain on the new path:

- `SavableABDC` as the common base of experiment concepts;
- OASM assembler/runtime objects in experiments or `BaseExp`;
- RB1 configuration or singleton construction inside CatSeq;
- `ExperimentRun`, legacy `ExpRunner`, or `AnalysisModule` compatibility types;
- JSON experiment persistence;
- a public analyzer-pipeline coordinator separate from `BaseExp`;
- a generic persistence interface with only the H5 implementation;
- per-point scheduler jobs or the deferred per-point hardware shot loop;
- re-export aliases from `rb1system.abstract` to `catseq.experiment`.

## Completion evidence

Interim acceptance evidence recorded on 2026-08-03:

- CatSeq commit `c084891` and rb1-next commit `aaa76e4` supplied the local
  experiment framework, compiler, runtime, and migrated RB1 consumers. CatSeq
  is not yet published at a version that rb1-next can pin.
- The rewritten `hardware-tests/chassis2_ttl.py` compiled
  `Chassis2TtlExp.build_sequence` to 125,000,000 logical cycles at 250 MHz with
  zero diagnostics. Its single `rwg0` plan contains `ttl_config`, high, wait,
  and low calls.
- The physical command completed through CatSeq `EthernetRuntime` on `eno1`
  with destination `60:cf:84:a7:bc:01`, reply node 21/channel 0, and
  `rwg0 -> node 2`; it exited successfully with terminal text
  `completed chassis 2 RWG0`.
- The retained record is
  `/home/hermes/workspaces/exp/hardware-tests/chassis2_ttl_20260803_231742.h5`.
  It is a readable 13,688-byte schema-1 `Chassis2TtlExp` record containing all
  six experiment groups and attempted execution index 0.

The full Rydberg hardware acceptance and CatSeq publication/version pin remain
open. When those gates close, append their evidence below rather than replacing
the TTL tracer record.

When the final phase closes, record in this document:

- the CatSeq and rb1-next commits used for acceptance;
- focused unit and integration test commands with pass counts;
- the `catseqc check` summary for the Rydberg entry;
- the TTL Compiled Sequence duration and terminal runtime evidence;
- the H5 output path and schema verification result.
