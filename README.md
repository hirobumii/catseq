# CatSeq

CatSeq is a categorical timing-composition language and native compiler for
RTMQ hardware sequences.

CatSeq 0.3 preserves the Python `Morphism`, `MorphismDef`, `>>`, `@`, `|`, and
channel-dictionary syntax. Production compilation is source based: `catseqc`
parses one `build_sequence` entry and its reachable service/module definitions,
then lowers them through native HIR and Morphism arenas to a complete
`OASMCallPlan`. It never imports or executes the experiment module.

## Installation

Release wheels are platform-specific and include both the Python package and
the native `catseqc` compiler. The supported release interpreter is Python
3.12.

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
from catseq.compilation import compile_entry, execute_oasm_calls

result = compile_entry(
    experiment.build_sequence,
    params,
    environment=environment,
)
calls = result.to_oasm_calls(opaque_callables=opaque_callables)
_, exp_sequence = execute_oasm_calls(calls, assembler_seq)
```

`compile_entry()` does not call the bound method. It uses it to locate the
source entry and to bind only restricted compile values. The result also
contains `logical_duration_cycles`, allowing a host such as `rb1-next.BaseExp`
to preserve its existing execution timeout contract.

The 0.2 `compile_to_oasm_calls(morphism, ...)` API and Python compiler passes
are intentionally removed. See [UPGRADING.md](UPGRADING.md).

## Compiler commands

The packaged `catseqc` executable provides:

```text
catseqc check
catseqc emit-hir
catseqc emit-arena
catseqc compile
```

The Python facade is the stable application API; the command-line interface is
primarily for diagnostics, CI, and compiler development.

## Development checks

```bash
uv run pytest -q
uv run ruff check catseq tests
cargo test --locked --workspace --all-targets --manifest-path rust/Cargo.toml
```

Architecture and accepted decisions are documented in
[docs/dev/0.3_native_compiler.md](docs/dev/0.3_native_compiler.md) and
[docs/adr](docs/adr).
