# CatSeq 0.4.2 quickstart

CatSeq is currently between frontend milestones. The new registered-source
frontend exists, but the public end-to-end compiler and execution facade do
not. This page therefore describes how to inspect and contribute to the source
boundary; it does not present an executable hardware quickstart.

## Install the development environment

Current CI, release artifacts, and physical deployment support Linux x86_64 only.
Use Python 3.12. Source builds require `clang-22`, `llvm-22-dev`, and
`libzstd-dev`, plus the names expected by NAC3's IRRT build:

```bash
CATSEQ_LLVM_TOOLS="$(mktemp -d)"
ln -s /usr/lib/llvm-22/bin/clang "$CATSEQ_LLVM_TOOLS/clang-irrt"
ln -s /usr/lib/llvm-22/bin/llvm-as "$CATSEQ_LLVM_TOOLS/llvm-as-irrt"
export PATH="$CATSEQ_LLVM_TOOLS:$PATH"
export LLVM_SYS_221_PREFIX=/usr/lib/llvm-22
uv sync --locked --all-extras --dev --python 3.12
```

The wheel contains the Python source surface, native frontend extension, and
low-level RTMQ runtime. It does not install `catseqc`.

## Review the source language

Start with [`../../frontend_demo/README.md`](../../frontend_demo/README.md).
In particular:

- `source_hir_loop_free.py` shows the exact `BaseExp.build_sequence(ExpParams)`
  entry and parameter-read boundary implemented by Issue #52;
- `source_hir_compute_reference.py` shows how a reachable `@compute` definition
  becomes an opaque, validated Compute reference in Typed Source HIR; and
- the remaining examples specify later Morphism and structured-Control work.

The demos are source fixtures, not ordinary CPython programs. `@kernel`,
`@compute`, Morphism constructors, and hardware intrinsics fail fast when
called directly because the native frontend owns their meaning.

## What is available now

The internal frontend starts from an actual experiment object and immutable
`ExpParams`, collects the exact registered entry and reachable definitions,
validates Compute source through NAC3, and returns target-independent Typed
Source HIR with provenance. It does not accept a caller-supplied source path,
qualified entry name, or compatibility fallback.

There is no supported public call that turns this HIR into a target program.
The removed `Compiler`, `CompiledSequence`, `EthernetRuntime`, and `catseqc`
interfaces must not be used during the migration. Later issues own public
analysis, canonical program construction, target lowering, linking, and the
high-level execution seam.

The independent low-level runtime remains usable for an already assembled OASM
program via `catseq.compilation.runtime`. It does not compile CatSeq source.
