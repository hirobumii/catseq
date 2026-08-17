# CatSeq development documentation

This directory contains project-development material. Device specifications
belong in [`../dev/`](../dev/).

## Release version

Use one command to set a release version instead of editing its copies by hand:

```bash
python3 tools/set_version.py X.Y.Z --date YYYY-MM-DD
```

`pyproject.toml` remains the reference version read by the release checker. The
command synchronizes it with the Python package, Rust workspace, both lockfiles,
README, quickstart, and a dated changelog section. Historical versioned
documents are not rewritten.

## Current documents

- [Frontend demos](../../frontend_demo/README.md) record the current
  registered-source language boundary. Issue #52 implements only exact
  entry-rooted analysis and target-independent Typed Source HIR; the public
  end-to-end compile path remains unavailable until downstream work lands.

## Historical records

- [Compilation and execution interface redesign](execution_api_redesign.md)
  records the removed 0.4 Compiler/CompiledSequence/EthernetRuntime facade.
- [Experiment-control clean-port plan](catseq_experiment_migration_plan.md)
  records how that former facade was integrated with BaseExp.
- [CatSeq 0.3 native compiler](0.3_native_compiler.md) records the completed
  0.3.2 compiler/runtime baseline.
- [CatSeq 0.3 Typed Source HIR implementation plan](0.3_typed_source_hir_plan.md)
  records the completed compiler milestone.
- [CatSeq 0.3.1 Linux raw-Ethernet runtime migration plan](0.3.1_linux_raw_ethernet_runtime_plan.md)
  records the completed runtime migration and hardware acceptance.
- [CatSeq 0.3.1 Rydberg-transfer pipeline performance](0.3.1_rydberg_transfer_pipeline_performance.md)
  records the corresponding performance checkpoint.
