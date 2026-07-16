# Changelog

All notable user-visible changes to CatSeq are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and CatSeq uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

The development version is `0.3.1.dev0` in Python metadata and the equivalent
Cargo prerelease `0.3.1-dev.0` in Rust metadata.

### Added

- Added the versioned compiler request as the byte-oriented in-process PyO3 API
  `catseq._native.compile()` while retaining the standalone native `catseqc`
  release artifact over the same Rust compiler core.

### Changed

- Changed `compile_entry()` to use the PyO3 compiler by default, eliminating
  compiler process startup and temporary environment, target, and binding JSON
  files. An explicitly selected external compiler remains available for
  diagnostics and compatibility testing.
- Changed platform wheels to contain one native extension and install `catseqc`
  as a console entry point over the same Rust CLI implementation, avoiding
  duplicate compiler machine code in the wheel.
- Consolidated current compiler status in
  `docs/dev/0.3_native_compiler.md`; older milestone plans are historical and
  no longer define the production path.

## [0.3.0] - 2026-07-15

### Added

- Added the standalone Rust `catseqc` compiler with `check`, `emit-hir`,
  `emit-arena`, and `compile` commands. The compiler reads a restricted Python
  sequencing language through the pinned NAC3 parser without importing or
  executing experiment modules.
- Added static source-bundle loading, import-aware reachability, typed Source
  HIR, resolved definition calls, compile-time attribute evaluation, and
  source-anchored diagnostics for the supported Python subset.
- Added a rustc-style on-disk incremental query graph with stable fingerprints,
  per-definition fingerprints and red-green invalidation boundaries, selected
  result caching, and atomic publication of successful sessions.
- Added Python-free canonical Morphism and Value Expression arenas with
  variadic Serial and Parallel nodes, shared definition bodies, channel-bound
  template instantiation, stable scan Runtime Slots, and relative timing.
- Added native specialization and RTMQ lowering through a complete versioned
  `OASMCallPlan` for the agreed 0.3 target slice, including TTL, RWG, RSP,
  hardware loops, global-sync epoch boundaries, and explicitly registered
  opaque host calls.
- Added platform wheels containing both the Python package and the native
  `catseqc` executable, plus `compile_entry()` as the stable Python facade for
  source compilation.
- Added integer `logical_duration_cycles` and target clock metadata to native
  compile results so host runtimes can preserve their execution timeout
  contract without constructing a Python Morphism for compilation.
- Added `@morphism_template` and `@atomic_morphism` source declarations. User
  templates can compose registered Atomic Schemas and compile through shared
  template segments and channel-bound `Instantiate` nodes.

### Changed

- Preserved the existing Python timing-composition API while moving source
  analysis, DAG construction, specialization, and OASM planning into Rust.
- Made source-level atomic operations logically cost-free; board-local OASM
  instruction occupancy and wait insertion are now owned by target lowering.
- Lowered composite hardware APIs as native templates instead of opaque Atomic
  operations. RWG `set_state` is now `load >> play`, and `linear_ramp` retains
  `load >> play >> Wait >> load >> play`; both use one `load` Atomic Schema and
  one `list[WaveformParams]` value type while preserving preload-to-exact-event
  deadlines and the same RTMQ calls.
- Moved scan-dependent scalar values to link-time Runtime Bindings while
  rejecting scan values that would change channels, call targets, event count,
  or other DAG topology.
- Removed the 0.2 Python Morphism compiler, its mutable event pipeline,
  Python DAG compiler session, instruction-cost analyzer, OASM precompiler,
  and Python subroutine compiler. Python now provides nominal source types and
  declarations only; production Morphism construction starts at a source entry
  and lives in Rust arenas.
- On 2026-07-14, a release build compiling
  `RydbergTransferExp.build_sequence` measured as follows on the development
  container. Cold samples use 20 unique caches; warm samples use 100 unchanged
  cache processes, and p95 uses nearest-rank selection. Wall time includes
  process startup, source discovery, cache I/O, and JSON serialization.

  | Command | Cold median / p95 | Warm median / p95 | Core lowering median (cold / warm) |
  | --- | ---: | ---: | ---: |
  | `check` | 90.2 / 92.2 ms | 5.12 / 6.86 ms | — |
  | `emit-arena` | 91.4 / 95.3 ms | 9.99 / 12.7 ms | HIR → arena: 0.047 / 0.041 ms |
  | `compile` | 108.8 / 112.3 ms | 29.0 / 31.7 ms | specialization + OASM: 16.1 / 16.3 ms |

- Unchanged warm runs reuse the on-disk typed frontend cache. Reusable
  specialization and OASM work products are not yet cached across processes.

## [0.2.4] - 2026-07-12

### Added

- Added RSP hardware morphisms and state transitions for initialization, carrier
  setup, static RF configuration, PID configuration, start, hold, release, and
  relink operations.
- Added configurable RSP initialization parameters and optional RWG hard reset
  control.
- Added amplitude and frequency trace support for spline ramps.

### Changed

- Made RSP atomic operations logically instantaneous at source level while
  accounting for their instruction occupancy during compilation.
- Pinned the OASM dependency to the lab-maintained revision used by CatSeq's
  compiler and hardware tests.

### Fixed

- Corrected RSP state transitions and the MUA register names used by PID release
  and relink operations.
- Preserved a Lane's trailing identity as a terminal timing marker so hardware
  loops include the complete logical duration of their repeated body.
- Made measured instruction costs replace, rather than add to, static fallback
  costs during batch timing analysis.
- Disassembled compiled instructions with each assembler node's actual board
  core instead of treating every board as an RWG.

### Performance

- Reduced repeated provenance copying during morphism composition.
- Batched instruction-cost analysis and optimized call-site trace collection.
- Avoided rescanning shared morphism objects during symbolic-expression checks.
