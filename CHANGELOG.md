# Changelog

All notable user-visible changes to CatSeq are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and CatSeq uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.4.1] - 2026-08-04

### Added

- Added the compiler-only `cycles(count)` constructor and the `Duration` source
  annotation so timing APIs can distinguish exact target cycles from ordinary
  `int` and `float` values.
- Added an executable README quickstart gate, enforced Python type checking,
  PyO3/stub surface parity checks, and fork-safe public CI coverage.

### Changed

- Made logical and TTL/RWG timing parameters require an explicit SI unit (`s`,
  `ms`, `us`, or `ns`) or `cycles(...)` (apart from neutral `identity(0)`),
  including values passed through locals, globals, user functions, environment
  fields, and scan bindings. Conversion uses the selected target clock
  and rejects non-integral Cycle Deltas instead of rounding. Negative values
  rewind the logical cursor; Epoch underflow is rejected, pulse/ramp widths
  remain non-negative, and rewinding loop bodies are expanded within an
  explicit compiler resource budget before scheduling.
- Scoped Environment Slot keys by stable entry-class or module-singleton
  identity, preventing fields on two instances of one class from colliding.
- Made host time conversion helpers require an explicit `clock_hz`; removed the
  implicit 250 MHz aliases `CLOCK_FREQ_HZ`, `CYCLE_DURATION_S`,
  `CYCLES_PER_US`, and `mu`.
- Removed the site-specific physical validation script and configuration from
  this repository. Offline transcript and downstream benchmark fixtures now
  use synthetic routes; real chassis acceptance belongs in a separate,
  site-private hardware-test workspace.

### Fixed

- Made simultaneous TTL writes deterministic with source-order last-write
  semantics per channel while retaining one coalesced board write.
- Rejected zero target clocks, normalized zero runtime timeout margins to one
  millisecond, and made default-timeout calculation overflow-safe.
- Made unknown typed OASM records fail at the Python decoder boundary with the
  record type, exact plan path, supported types, and extension guidance.
- Changed the built-in RTMQ target to strict duration quantization so an
  inexact time cannot silently become a different hardware duration.

## [0.4.0] - 2026-08-04

### Added

- Added the focused `catseq.experiment` modules for host-side experiment
  lifecycle control, immutable scan parameters, Descartes traversal, devices,
  analyzers, panel publication, and H5 persistence. `BaseExp` compiles
  only `build_sequence` and executes the returned `CompiledSequence` through a
  supplied runtime. The first scan point compiles synchronously; later points
  compile one point ahead while the current sequence runs, and wait only when
  the prefetched compilation is not yet complete. Unused speculative work does
  not delay cleanup after failure or cancellation.
- Added `tools/set_version.py` as the single release-version command for Python,
  Rust, lockfiles, current user documentation, and the dated changelog section.

### Changed

- Moved downstream opaque operations out of CatSeq's built-in RTMQ target
  profile. Systems supply their own opaque callables through `Compiler`
  configuration, and the native compiler now treats those declared definitions
  as opaque leaves instead of parsing their Python bodies.

### Fixed

- Restored the `catseq.hardware.rsp.pid_relink` source declaration already
  recognized by the native compiler.

## [0.3.2] - 2026-08-03

### Added

- Added a reusable, system-scoped `Compiler` whose Compile Environment, target
  profile, source root, and incremental cache are owned by a native Rust
  compiler session. `Compiler.from_system()` accepts typed channel declarations,
  opaque encoder callables, and scalar environment values once instead of
  requiring a raw environment dictionary for every sequence.
- Added the immutable, Rust-owned `CompiledSequence` returned by
  `Compiler.compile()`. It exposes the OASM Call Plan, logical duration, target
  clock, diagnostics, and incremental compilation evidence without exposing an
  assembler or physical execution state.
- Added `EthernetRuntime`, which owns the chassis destination, reply endpoint,
  and logical-board routes and executes a `CompiledSequence` with
  `runtime.run(compiled)`.

### Changed

- Moved OASM assembler construction and final instruction encoding behind the
  `EthernetRuntime` facade. OASM remains the pinned RTMQ instruction encoder,
  but its assembler, core types, mutable contexts, and interface shims are no
  longer part of the common experiment API.
- Made the public Ethernet runtime derive its timeout from the compiled logical
  duration plus a configurable margin. Schema versions, instruction capacities,
  transport implementation names, and low-level board endpoint objects remain
  internal defaults in the common path.
- Removed the 0.3.1 `compile_entry()`, `assemble_oasm_calls()`, and
  `execute_oasm_program()` helpers from public package exports. Their internal
  modules remain available to CatSeq's regression and migration tooling, but
  are not application compatibility seams.

### Fixed

- Preserved OASM's completion epilogue when using an explicit runtime reply
  endpoint. The private adapter now supplies the endpoint during encoding, so
  RTMQ boards emit terminal completion evidence instead of timing out after a
  successful launch.

## [0.3.1] - 2026-07-24

### Added

- Added an in-process PyO3 compiler backend for the public `compile_entry()`
  facade while retaining the standalone native `catseqc` release artifact over
  the same Rust compiler core.
- Added `assemble_oasm_calls()`, which populates the supplied OASM assembler
  contexts, clearing them by default, then finalizes copies into an immutable,
  Rust-owned `AssembledOASMProgram`. It performs no network or device I/O, and
  appends runtime completion instructions only to the copied contexts.
- Added configurable Linux raw-Ethernet execution through
  `execute_oasm_program()`, `LinuxRawEthernetRuntimeConfig`, and
  `BoardEndpoint`. The one-shot execution call downloads and runs one assembled
  program, then monitors every configured board; there is no separate public
  download-only operation. It returns `OASMRuntimeSuccess` only after every
  board reaches a trusted terminal completion.
- Added structured runtime outcomes and `CatSeqRuntimeError` evidence, including
  execution certainty, per-board execution evidence, device exceptions, and
  diagnostic details. Runtime failures raise `CatSeqRuntimeError` with the
  native `OASMRuntimeFailure` evidence attached.

### Changed

- Changed `compile_entry()` to use the PyO3 compiler by default, eliminating
  compiler process startup and temporary environment, target, and binding JSON
  files. An explicitly selected external compiler remains available for
  diagnostics and compatibility testing.
- Changed platform wheels to contain one native extension and install `catseqc`
  as a console entry point over the same Rust CLI implementation, avoiding
  duplicate compiler machine code in the wheel.
- Moved Download-loader materialization, RTLink framing, retry handling, raw
  Ethernet transmission, and completion monitoring into Rust. OASM remains the
  instruction encoder but no longer owns the supported network execution path.
- Made Linux physical execution use `AF_PACKET/SOCK_RAW` without pcap. The
  invoking process needs `CAP_NET_RAW`; root or `sudo` is not otherwise part of
  the interface contract.
- Consolidated current compiler status in
  `docs/development/0.3_native_compiler.md`; older milestone plans are
  historical and no longer define the production path.

### Fixed

- Fixed Linux raw-Ethernet transmission on connectionless `AF_PACKET` sockets
  by providing the selected interface and destination explicitly for every
  frame.

### Removed

- Removed `execute_oasm_calls()`, which combined OASM assembler population with
  an implicit mock fallback. Callers now explicitly convert
  `OASMCompileResult` to OASM calls and assemble an in-memory program with
  `assemble_oasm_calls()`.
- Removed supported execution through OASM `assembler.run()` or
  `sequence.run()`. Physical execution now uses `execute_oasm_program()` and is
  owned by the Rust runtime.

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
