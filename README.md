# CatSeq

[![CI](https://github.com/hirobumii/catseq/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/hirobumii/catseq/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/hirobumii/catseq)](https://github.com/hirobumii/catseq/releases)
![Python](https://img.shields.io/badge/python-3.12-blue.svg)
![Rust](https://img.shields.io/badge/rust-1.88%2B-orange.svg)

CatSeq 0.4.2 is a categorical timing-composition language and an RTMQ
frontend/runtime workspace for hardware sequences.

## Current implementation boundary

The repository is migrating from the discarded 0.4 end-to-end compiler to a
new exact registered-source frontend. The implemented frontend currently:

- collects the `@kernel` entry and its reachable registered definitions from
  an actual `BaseExp` object;
- resolves definitions by registered Python object identity, not by a path or
  qualified-name fallback;
- validates reachable `@compute` definitions through the pinned CatSeq NAC3
  fork; and
- produces target-independent, Python-free Typed Source HIR plus Compute
  identities and source provenance.

This frontend is an internal migration interface. There is currently no public
end-to-end `Compiler`, `CompiledSequence`, `EthernetRuntime`, `catseqc`, or
standalone compiler artifact. Public analysis, lowering, linking, and execution
will be exposed only after their downstream contracts are implemented. Code
must not fall back to the removed compiler path while that work is incomplete.
`BaseExp` remains the registered-source owner, but `BaseExp.run()` fails before
performing any experiment lifecycle work.

The low-level Rust-owned RTMQ/OASM runtime remains available independently. It
accepts an already assembled OASM program and explicit physical routing; it
does not compile CatSeq source.

The reviewable source boundary lives in [`frontend_demo/`](frontend_demo/).
Those examples deliberately include both implemented and proposed frontend
forms and are not an end-user executable quickstart.

## Installation

Current CI, release artifacts, and physical deployment support Linux x86_64 only.
The supported release interpreter is Python 3.12. The wheel contains the Python
source surface, the native frontend extension, and the low-level runtime. It
does not install a `catseqc` command.

Source builds require `clang-22`, `llvm-22-dev`, and `libzstd-dev`, together
with the tool names expected by NAC3's IRRT build:

```bash
CATSEQ_LLVM_TOOLS="$(mktemp -d)"
ln -s /usr/lib/llvm-22/bin/clang "$CATSEQ_LLVM_TOOLS/clang-irrt"
ln -s /usr/lib/llvm-22/bin/llvm-as "$CATSEQ_LLVM_TOOLS/llvm-as-irrt"
export PATH="$CATSEQ_LLVM_TOOLS:$PATH"
export LLVM_SYS_221_PREFIX=/usr/lib/llvm-22
uv sync --locked --all-extras --dev --python 3.12
```

The pinned CatSeq NAC3 fork is public. Release wheels carry the compiled
extension and require no local LLVM installation.

## Source model

CatSeq retains the compiler-only Python surface for `Morphism`, `@morphism`,
`>>`, `|`, `@kernel`, and `@compute`. Calling these
definitions as ordinary CPython functions fails fast: their bodies are source
for the native frontend, not a second executable implementation.

Timing remains an explicit compositional value. Physical durations use SI
units such as `us` or `ms`; intentional target-cycle values use `cycles(...)`.
The frontend demos show multi-channel, multi-board, Compute, and structured
Control source contracts without pretending that downstream compilation is
already available.

## Low-level runtime

The independent runtime surface is in `catseq.compilation.runtime`:

- `AssembledOASMBoard` and `AssembledOASMProgram` describe an already assembled
  program;
- `BoardEndpoint` and `LinuxRawEthernetRuntimeConfig` describe explicit
  deployment routing; and
- `execute_oasm_program()` downloads and monitors that program.

Physical execution is Linux-only, uses `AF_PACKET/SOCK_RAW`, and requires
`CAP_NET_RAW`. The runtime does not infer routes and does not accept CatSeq
source or Typed Source HIR.

## 0.4.2 API boundary

The currently supported public Python surface is the restricted-source DSL,
host experiment data/control modules, and the low-level assembled-program
runtime. The exact registered frontend adapter is private while the migration
is incomplete.

The removed 0.4 `Compiler`, `CompiledSequence`, `EthernetRuntime`, and `catseqc`
facilities are not compatibility APIs. Earlier release and design records that
describe them are historical evidence, not current instructions.

## Development checks

```bash
uv run pytest -q
uv run mypy catseq
uv run ruff check catseq tests tools frontend_demo
cargo fmt --all --manifest-path rust/Cargo.toml -- --check
cargo +1.88.0 clippy --locked --workspace --all-targets \
  --manifest-path rust/Cargo.toml -- -D warnings
cargo test --locked --workspace --all-targets --manifest-path rust/Cargo.toml
git diff --check
```

The [development documentation index](docs/development/README.md) identifies
the current migration boundary and historical implementation records. The
top-level [documentation index](docs/README.md) separates user, device,
development, and decision records.
