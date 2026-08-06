# CatSeq

[![CI](https://github.com/hirobumii/catseq/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/hirobumii/catseq/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/hirobumii/catseq)](https://github.com/hirobumii/catseq/releases)
![Python](https://img.shields.io/badge/python-3.12-blue.svg)
![Rust](https://img.shields.io/badge/rust-1.88%2B-orange.svg)

CatSeq 0.4.2 is a categorical timing-composition language, native compiler,
RTMQ execution runtime, and host-side experiment controller for hardware
sequences.

CatSeq 0.4.2 preserves the Python `Morphism`, `MorphismDef`, `>>`, `@`, `|`, and
channel-dictionary syntax. The public `Compiler` parses one sequence entry and
its reachable definitions, then lowers them to a Rust-owned
`CompiledSequence`. `EthernetRuntime` separately owns physical chassis routing
and execution. The `catseqc` command is a diagnostic and automation adapter
over the same Rust compiler core.

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

## Compile a TTL sequence

Save this complete compile-only example as `quickstart_ttl.py` and run it with
`uv run python quickstart_ttl.py`:

<!-- catseq-release-check: quickstart:start -->
```python
from pathlib import Path

from catseq import Compiler
from catseq.hardware.ttl import initialize, pulse
from catseq.morphism import Morphism, identity
from catseq.time_utils import ms
from catseq.types import Board, Channel, ChannelType


rwg0 = Board("rwg0")
ttl0 = Channel(rwg0, local_id=0, channel_type=ChannelType.TTL)


class TtlExperiment:
    def build_sequence(self) -> Morphism:
        return identity(0) >> {ttl0: initialize() >> pulse(500 * ms)}


class LabSystem:
    source_root = Path(__file__).parent
    channels = {"quickstart_ttl.ttl0": ttl0}


compiler = Compiler.from_system(LabSystem())
compiled = compiler.compile(TtlExperiment().build_sequence)

print(f"compiled {compiled.logical_duration_cycles} cycles")
print(compiled.oasm_call_plan)
```
<!-- catseq-release-check: quickstart:end -->

The first line is `compiled 125000000 cycles`: 500 ms at the default 250 MHz
target clock. `Compiler.compile()` uses the bound method to locate the source
entry but does not call it. The method body and reachable CatSeq definitions
are parsed by the native compiler, so arbitrary Python lifecycle code is not
executed during compilation.

Hardware time arguments are explicit: use `500 * ms` (or another SI unit) for
a physical duration, and `cycles(count)` for an intentional target Cycle
Delta. Bare numeric values in `identity`, `pulse`, `hold`, `rf_pulse`, and
`linear_ramp` are compile errors, except for the neutral `identity(0)` spelling.
Conversion uses the selected target clock and never rounds
an inexact Cycle Delta. A negative `Duration` passed to `identity` or `hold`
rewinds the logical cursor within the current Epoch; pulse and ramp widths stay
non-negative. The compiler rejects Epoch underflow and expands a rewinding
loop body before scheduling instead of encoding an invalid hardware loop.

The fully qualified channel key includes the source module name. Keep the
documented filename `quickstart_ttl.py`, or update
`LabSystem.channels["<module>.ttl0"]` to match the filename you choose.

`Compiler.from_system()` captures the source root and typed channel map once.
A system may additionally provide `opaque_calls`, scalar `environment_values`,
a target profile, and an incremental `cache_dir`. Environment keys use their
stable compile-instance identity (for example,
`quickstart_ttl.Experiment.rewind` for an entry class or
`quickstart_ttl.service.rewind` for a module singleton); a `Duration` value is
a signed target Cycle Delta.

Compile-reachable immutable updates of CatSeq Native Records use
`catseq.replace(record, **changes)`, not `dataclasses.replace`. This is a
compiler-only special form: the Rust frontend validates the record schema,
field names, and field value types before arena lowering.

## Compose downstream OASM with a blackbox

Use `black_box` when a downstream module must emit raw OASM while CatSeq
continues to own timing, board-level composition, and conflict checking:

```python
from catseq.morphism import Morphism
from catseq.oasm import black_box


def emit_raw_oasm() -> None:
    # Site-owned OASM instructions stay in the downstream repository.
    ...


def blackbox_sequence() -> Morphism:
    return black_box(
        duration_cycles=12,
        board_funcs={rwg_board: emit_raw_oasm},
    )
```

The callback must be a module-level function. CatSeq does not execute the
sequence builder or serialize a Python callable into its native arenas;
instead, it stores the callback's stable source identity in the OASM Call Plan
and retains the live callable only in the host-side `CompiledSequence`.
Captured values therefore belong in `user_args` or `user_kwargs`, rather than
in a nested function or lambda. The `board_funcs` keys are the participating
boards and receive one callback each. No downstream Atomic Schema or channel
state declaration is required for this source-level blackbox. Module-qualified
callbacks and callbacks in a directly executed source file retain stable source
identities for host-side resolution.
`duration_cycles` is each callback's declared board occupancy; the callback
must emit exactly that duration, and CatSeq does not append a second wait for
the same interval. Board occupancy is exclusive and half-open: any ordinary
same-board morphism whose occupancy intersects the region is rejected, including
one that begins earlier and spans it. A morphism or another black box may start
exactly at the region's end.
CatSeq deliberately does not inspect or track state changes made by raw OASM.
The user must preserve state or explicitly re-establish it before composing a
later state-dependent native operation.

## Run on RTMQ hardware

Physical routing is deployment configuration, not sequence source. For
example, a host application can read its route from environment or site
configuration and run the compiled value:

```python
import os

from catseq import EthernetRuntime


runtime = EthernetRuntime(
    interface=os.environ["CATSEQ_INTERFACE"],
    destination=os.environ["CATSEQ_CHASSIS_MAC"],
    reply=(
        int(os.environ["CATSEQ_REPLY_NODE"]),
        int(os.environ.get("CATSEQ_REPLY_CHANNEL", "0")),
    ),
    boards={"rwg0": int(os.environ["CATSEQ_RWG0_NODE"])},
)

result = runtime.run(compiled)
print(result.board_evidence)
```

`EthernetRuntime.run()` privately invokes the pinned OASM instruction encoder,
then passes the immutable program to the Rust Download/RTLink runtime. Physical
execution is currently Linux-only, uses `AF_PACKET/SOCK_RAW` without pcap, and
requires `CAP_NET_RAW`. The timeout defaults to the compiled logical duration
plus the runtime margin. Real interface, MAC, reply-node, and board-route values
belong in the consuming application or hardware-test repository, not CatSeq.

## Coordinate an experiment run

`catseq.experiment` provides ordinary host-side Python control around the
per-scan-point compiler/runtime boundary. Import concepts from the focused
module that owns them; the package does not provide a bulk re-export facade:

```python
from catseq.experiment.base_exp import BaseExp
from catseq.experiment.base_module import BaseModule, BaseService
from catseq.experiment.params import ExpParam, ExpParams, ScanPoint
```

`BaseExp.run()` owns repeat/scan traversal, device lifecycle, analyzers, panel
publication, H5 persistence, and cleanup. It compiles the first point
synchronously, then compiles point N+1 while the compiled sequence for point N
runs. If that compilation is still in progress when traversal reaches N+1,
execution waits for it. Only `build_sequence` and the immutable point
`ExpParams` enter the compiler; experiment orchestration itself is never
compiled.

The concrete runner supplies the system-scoped `Compiler`, runtime, devices,
run control, panel publisher, and `H5Writer`. Hardware locks, process policy,
MQTT transport, and platform-specific device implementations remain in the
consumer rather than CatSeq.

## 0.4.2 API boundary

`Compiler`, `CompiledSequence`, and `EthernetRuntime` are the stable application
seam. The compiled sequence is immutable and contains the OASM Call Plan,
logical duration, target clock, diagnostics, and incremental evidence without
exposing an assembler or transport state.

The host experiment seam consists of the focused `catseq.experiment.*` modules,
with `BaseExp` as the only complete-lifecycle coordinator. There is no separate
`ExperimentRun` object, and neither the experiment package nor top-level
`catseq` re-exports the entire experiment API.

The 0.3.1 `compile_entry()`, `assemble_oasm_calls()`, and
`execute_oasm_program()` implementation helpers are no longer exported as
public APIs. Internal modules retain the adapters needed for compiler and
runtime regression tests.

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

The command-line interface is primarily for diagnostics, CI, compiler
development, and explicit external-compiler compatibility checks.
`emit-arena` and `compile` require `--target-profile` because SI-unit lowering
cannot be performed without the selected target clock.

## Development checks

```bash
uv run pytest -q
uv run mypy catseq
uv run ruff check catseq tests tools benchmarks
cargo fmt --all --manifest-path rust/Cargo.toml -- --check
cargo +1.88.0 clippy --locked --workspace --all-targets \
  --manifest-path rust/Cargo.toml -- -D warnings
cargo test --locked --workspace --all-targets --manifest-path rust/Cargo.toml
git diff --check
```

`benchmarks/rydberg_transfer_pipeline.py` is an offline downstream-RB1
benchmark, not a CatSeq CI gate. It uses only synthetic routes and a nonexistent
interface. Real interface, MAC, node, and route configuration belongs in the
site-private hardware-test workspace outside this repository.

The [development documentation index](docs/development/README.md) identifies
the current interface and migration records. The top-level
[documentation index](docs/README.md) separates user, device, development, and
decision records.
