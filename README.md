# CatSeq

[![CI](https://github.com/hirobumii/catseq/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/hirobumii/catseq/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/hirobumii/catseq)](https://github.com/hirobumii/catseq/releases)
![Python](https://img.shields.io/badge/python-3.12-blue.svg)
![Rust](https://img.shields.io/badge/rust-1.88%2B-orange.svg)

CatSeq is a categorical timing-composition language and native compiler for
RTMQ hardware sequences.

CatSeq 0.3 preserves the Python `Morphism`, `MorphismDef`, `>>`, `@`, `|`, and
channel-dictionary syntax. Production compilation is source based: the public
`compile_entry()` facade sends a versioned request to the in-process PyO3
extension, which parses one `build_sequence` entry and its reachable
service/module definitions and lowers them to a complete `OASMCallPlan`. It
never imports or executes the experiment module. The `catseqc` command is a
diagnostic and automation adapter over the same Rust compiler core.

## Installation

Release wheels are platform-specific and include the Python package, its PyO3
compiler extension, and the `catseqc` console command. Standalone native
`catseqc` archives are also published for non-Python automation. The supported
release interpreter is Python 3.12.

For development from a checkout:

```bash
uv sync --locked --all-extras --dev --python 3.12
```

No platform setup script is required.

## Sequence source

```python
from catseq.hardware.ttl import hold, set_high, set_low
from catseq.morphism import Morphism, MorphismDef, identity, morphism_template
from catseq.time_utils import us


@morphism_template
def pulse(duration: float) -> MorphismDef:
    return set_high() >> hold(duration) >> set_low()


class PulseExperiment:
    def build_sequence(self, params) -> Morphism:
        return identity(10 * us) >> {
            self.trigger: pulse(params["duration_us"] * us)
        }
```

`MorphismDef` is the source spelling of `MorphismTemplate`. Its body may compose
Atomic Schemas with `>>`, `@`, and `|`; the compiler stores the body once and
binding it to a channel creates an `Instantiate` node. Calling this source with
CPython raises `CompilerOnlyError` because Python no longer owns a shadow arena.

## Native compilation

The host application owns its hardware channel map, opaque callable registry,
and OASM assembler. CatSeq ships the fixed RTMQ target profile:

```python
from catseq.compilation import (
    BoardEndpoint,
    LinuxRawEthernetRuntimeConfig,
    assemble_oasm_calls,
    compile_entry,
    execute_oasm_program,
)

result = compile_entry(
    experiment.build_sequence,
    params,
    environment=environment,
)
calls = result.to_oasm_calls(opaque_callables=opaque_callables)
program = assemble_oasm_calls(calls, assembler_seq)
runtime = LinuxRawEthernetRuntimeConfig(
    1,
    "eno1",
    None,  # defaults to interface MAC + 2
    2_000,
    [BoardEndpoint("rwg0", 2, 0, 131_072)],
)
success = execute_oasm_program(program, runtime)
```

`compile_entry()` does not call the bound method. It uses it to locate the
source entry and to bind only restricted compile values, then sends a
versioned, Python-free request to the in-process PyO3 compiler. The result also
contains `logical_duration_cycles`, allowing a host such as `rb1-next.BaseExp`
to preserve its existing execution timeout contract.

`assemble_oasm_calls()` only encodes an immutable in-memory ICH program.
`execute_oasm_program()` passes that Rust-owned value directly through PyO3 to
the Rust Download/RTLink runtime. Physical execution is Linux-only, uses
`AF_PACKET/SOCK_RAW` without pcap, and requires `CAP_NET_RAW`.

The 0.2 `compile_to_oasm_calls(morphism, ...)` API and Python compiler passes
are intentionally removed. See [UPGRADING.md](UPGRADING.md).

## Compiler commands

The packaged `catseqc` command provides:

```text
catseqc check
catseqc emit-hir
catseqc emit-arena
catseqc compile
```

The Python facade and its `OASMCompileResult` are the stable application seam.
The command-line interface is primarily for diagnostics, CI, compiler
development, and explicit external-compiler compatibility checks.

## Development checks

```bash
uv run pytest -q
uv run ruff check catseq tests tools benchmarks
cargo fmt --all --manifest-path rust/Cargo.toml -- --check
cargo +1.88.0 clippy --locked --workspace --all-targets \
  --manifest-path rust/Cargo.toml -- -D warnings
cargo test --locked --workspace --all-targets --manifest-path rust/Cargo.toml
git diff --check
```

The authoritative implementation status is
[docs/dev/0.3_native_compiler.md](docs/dev/0.3_native_compiler.md). Accepted
decisions are recorded in [docs/adr](docs/adr).
