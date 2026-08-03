---
status: accepted
---

# Put generic experiment control in `catseq.experiment`

CatSeq owns the generic experiment-control concepts under
`catseq.experiment`. This includes `BaseExp`, `BaseModule`, `BaseService`, scan
and parameter traversal, result and device lifecycle bases, analyzer and panel
contracts, and concrete H5 persistence.

`catseq.experiment` is a namespace, not a bulk re-export facade. Each cohesive
public module owns its own interface: for example, callers import `BaseExp`
from `catseq.experiment.base_exp`, `BaseModule` and `BaseService` from
`catseq.experiment.base_module`, and panel types from
`catseq.experiment.panel`.

`BaseExp` is the lifecycle coordinator for one complete experiment execution.
It does not discover RB1 configuration or construct target-specific runtimes,
devices, H5 files, or panel transports. Those collaborators are supplied by the
concrete experiment or its runner, so the generic flow can be reused without
importing deployment policy into CatSeq. A separate `ExperimentRun` concept is
not introduced.

Experiment orchestration remains ordinary host Python. `BaseExp` invokes the
CatSeq compiler with only the bound `build_sequence` method and one immutable
point's `ExpParams`; traversal, device lifecycle, analysis, publication,
persistence, and cleanup are never compiled. The first attempted point compiles
synchronously. Later points compile one point ahead while the current sequence
runs, so cancellation or failure may leave one compiled point that was never
attempted. BaseExp waits for that result only if traversal reaches the point and
does not delay cleanup for an unused speculative compilation.

`BaseModule` and `BaseService` are clean ports of the existing sequence
abstractions with serialization removed. CatSeq does not add a separate
authoring base or require the compiler to classify these host-side types.

RB1 retains only platform adapters and concrete experiment implementations.
Migrated consumers import the specific `catseq.experiment.*` modules directly;
CatSeq does not provide lookalike Raw classes, and `rb1system.abstract` does not
become a compatibility re-export layer.

The phased clean port and its acceptance gates are recorded in the
[experiment-control migration plan](../development/catseq_experiment_migration_plan.md).
