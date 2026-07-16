# CatSeq development guide

CatSeq is a Python 3.12 restricted-source DSL backed by a Rust 2024 native
compiler. The authoritative current architecture and implementation status is
[`docs/dev/0.3_native_compiler.md`](docs/dev/0.3_native_compiler.md). ADRs under
[`docs/adr`](docs/adr) record accepted decisions. Historical milestone plans
are context only and are labelled as such.

## Production path

Applications call `catseq.compilation.compile_entry()`. It identifies the
source entry and restricted argument bindings without executing the entry, then
sends a versioned, Python-free request to `catseq._native.compile(bytes)`. The
PyO3 extension calls `compile_json_request()`; `catseqc` invokes the CLI layer
from the same Rust compiler library. The compiler emits a versioned
`OASMCallPlan`; Python adapts that plan to the host-owned OASM assembler.

The in-process PyO3 route is the default production path. `catseqc` is the CLI
adapter for diagnostics, CI, standalone automation, and explicit compatibility
checks. Do not introduce a second compiler implementation or a Python-owned
shadow arena.

## Repository boundaries

- `catseq/` owns the public Python source vocabulary, `compile_entry()` facade,
  result types, and OASM execution adapter.
- `rust/catseq-frontend` owns static loading, parsing, reachability, Source HIR,
  type analysis, diagnostics, and the incremental query session.
- `rust/catseq-core` owns compiler data structures and canonical arenas.
- `rust/catseq-compiler` owns the shared request-to-response compiler entry.
- `rust/catseq-rtmq` owns RTMQ target lowering and `OASMCallPlan` emission.
- `rust/catseq-python` and `rust/catseqc` are thin PyO3 and CLI adapters.

Consumer repositories own their source bundles, compile environments, hardware
maps, opaque callable registries, OASM assemblers, and end-to-end differential
acceptance tests. CatSeq must not import or depend on a consumer repository.

## Implementation rules

- Preserve the public restricted-source spelling (`Morphism`, `MorphismDef`,
  `>>`, `@`, `|`, and channel dictionaries) unless an accepted change says
  otherwise.
- Keep compiler requests and responses versioned and free of live Python
  objects, Python AST nodes, or consumer-specific types.
- Keep scheduling, state analysis, scan evaluation, and RTMQ instruction
  occupancy in Rust. The Python OASM adapter only resolves registered host
  callables and translates plan records to assembler calls.
- Treat `compile_entry()` and `OASMCompileResult` as the application seam.
  `_native.compile(bytes)` and `compile_json_request()` are lower-level shared
  transport/compiler seams.
- Use SI seconds in Python APIs; callers express other units with
  `catseq.time_utils` constants. Native target lowering converts durations to
  checked integer cycles.
- Add parameter and return annotations to public Python functions. Follow the
  repository Ruff configuration rather than copying style rules into docs.
- Keep Rust compatible with the workspace MSRV (1.88) and edition (2024).
- Do not re-enable the retained tree-sitter compatibility frontend. Its removal
  is a separate cleanup change with its own verification boundary.

## Versions

Python metadata uses PEP 440 and Rust metadata uses SemVer. During this
development cycle they are `0.3.1.dev0` and `0.3.1-dev.0` respectively; these
are ecosystem-native spellings of the same prerelease.

## Required checks

Run the relevant focused tests while editing, then before commit run:

```bash
uv run ruff check catseq tests benchmarks
uv run pytest -q
cargo fmt --all --check --manifest-path rust/Cargo.toml
cargo +1.88.0 clippy --locked --workspace --all-targets --manifest-path rust/Cargo.toml -- -D warnings
cargo test --locked --workspace --all-targets --manifest-path rust/Cargo.toml
git diff --check
```

Packaging or compiler-adapter changes also require rebuilding the extension and
binary, checking both reported versions, and running an installed-wheel smoke
test that calls `catseq._native.compile()`. Consumer compatibility is verified
in the consumer repository, not by adding consumer fixtures to CatSeq.
