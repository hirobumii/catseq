# CatSeq 0.4.2 quickstart

CatSeq 0.4.2 keeps the Python Morphism composition syntax, but production
compilation starts from a source definition. It does not execute the Python
builder and does not compile an already-constructed Python `Morphism`.

## Install

Install the platform wheel for Python 3.12. The wheel contains both the
`catseq` package and the native `catseqc` compiler.

For a source checkout, use uv:

```bash
uv sync --locked --all-extras --dev --python 3.12
```

Building from source also requires LLVM 22 development libraries. Set
`LLVM_SYS_221_PREFIX` if that LLVM installation is not on the build path. The
pinned CatSeq NAC3 fork is public. Installing a release wheel requires no local
LLVM installation.

## Compile a sequence

Save this complete compile-only example as `quickstart_ttl.py`:

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

Run it with `uv run python quickstart_ttl.py`. The first line is
`compiled 125000000 cycles`.

`pulse` and other hardware timing APIs require an explicit duration. Use an SI
unit such as `500 * ms`, or use `cycles(count)` when the value intentionally
means target cycles. A bare numeric value is rejected, and an SI duration that
is not an exact Cycle Delta for the selected target clock is also rejected.

The channel key is qualified by the source module. Keep the documented
`quickstart_ttl.py` filename, or replace `quickstart_ttl.ttl0` with the module
name of the file you create.

`Compiler.from_system()` reads `source_root` and `channels` from the system. A
system may also supply `opaque_calls`, scalar `environment_values`, a target
profile, and an incremental `cache_dir`; these are captured once by the
Rust-owned compiler session. `Compiler.compile()` uses the method only to
locate its source and bind restricted arguments. Explicit root scalar arguments
are Compile-known specialization inputs, while scan mapping entries remain
Link-time Runtime Slots. The method body and reachable service/module
definitions are parsed by the Rust compiler; arbitrary host lifecycle code is
not compiled.

An annotated class field without a source initializer is an Environment Slot.
Use `<module>.<entry-class-or-singleton>.<field>` as the `environment_values`
key (for example, `quickstart_ttl.Experiment.rewind`); this keeps fields on two
instances of the same class distinct. A `Duration` binding is a signed target
Cycle Delta.

## Update a Native Record

Use `catseq.replace` inside compile-reachable source when a sequence needs an
immutable update of a CatSeq Native Record:

```python
from catseq import replace
from catseq.hardware.rwg import initialize, set_state
from catseq.morphism import Morphism, identity
from catseq.types import Board, Channel, ChannelType, StaticWaveform


rwg_board = Board("rwg0")
rwg_channel = Channel(rwg_board, local_id=0, channel_type=ChannelType.RWG)
target = StaticWaveform(freq=1.0, amp=0.2, sbg_id=0)


def waveform_sequence() -> Morphism:
    updated = replace(target, freq=2.0)
    return identity(0) >> {
        rwg_channel: initialize(80.0) >> set_state([updated])
    }
```

`replace` is a compiler-only special form rather than a host-side dataclass
helper. The Rust frontend preserves the Native Record type and validates every
changed field name and value type. Calling it directly in ordinary CPython
host code raises `CompilerOnlyError`.

## Use a source-level OASM blackbox

`catseq.oasm.black_box` keeps raw, downstream OASM encoders composable
until the OASM backend is replaced:

```python
from catseq.morphism import Morphism
from catseq.oasm import black_box


def emit_raw_oasm() -> None:
    ...  # Site-owned OASM instructions.


def sequence() -> Morphism:
    return black_box(
        duration_cycles=12,
        board_funcs={board: emit_raw_oasm},
        user_args=(),
        user_kwargs={},
    )
```

The native arena records the exact duration and one callback identity per
participating board. The OASM Call Plan contains only stable callback identities
and native data; the Python assembly adapter resolves the live functions from
the returned `CompiledSequence`.

Callbacks must be module-level functions. Nested functions and lambdas capture
Python objects that the source compiler deliberately does not execute or
serialize. Pass captured scalar or native-record data through `user_args` or
`user_kwargs`. The `board_funcs` keys define the participating boards, with one
callback per board. Each board is exclusively occupied for `[start, end)`: any
ordinary same-board morphism whose occupancy intersects the interval is invalid,
including one that begins earlier and spans the blackbox. A morphism may begin
exactly at the end boundary.
Adjacent same-board blackboxes may share an end/start boundary; genuine
overlaps remain invalid.
`duration_cycles` declares the callback's own exact board occupancy: the
callback must emit that duration, and CatSeq does not add another wait after it.
The blackbox declares no channel state, and CatSeq does not inspect state changes
made by raw OASM. Preserve state or explicitly re-establish it before a later
state-dependent native operation.

## Run a compiled sequence

Runtime routing is deployment configuration and stays separate from the
compile-only sequence above:

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

The old `compile_to_oasm_calls(morphism, ...)` API is removed in 0.3. Native
compiler diagnostics and RTMQ lowering tests now own that behavior.

The returned `CompiledSequence` is an immutable Rust/PyO3 value. OASM assembly
is private to `EthernetRuntime.run()` and does not leave a mutable sequence to
run later. Execution is currently Linux-only and requires `CAP_NET_RAW`; Rust
uses `AF_PACKET/SOCK_RAW` directly and does not use pcap.
