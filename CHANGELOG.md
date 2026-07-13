# Changelog

All notable user-visible changes to CatSeq are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and CatSeq uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Started the 0.3 `catseqc` DAG-native compiler development line.
- Added a restricted-Python source frontend that discovers sequence entry
  points without importing or executing experiment modules.
- Added source HIR lowering for assignments, calls, attributes, subscripts,
  literals, containers, arithmetic, and timing-composition operators.
- Added import-aware call-target resolution and stable runtime slots for scan
  parameter uses.
- Enforced typed `ExpParams` scan discovery, lexical parameter shadowing,
  root-reachable analysis, and rejection of scan-dependent topology.
- Added a shared segmented arena with zero-copy template instantiation.
- Preserved the Python timing-composition syntax while moving compiler-owned
  storage to Rust.

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
