# CatSeq 0.3.2 quickstart

CatSeq 0.3.2 keeps the Python Morphism composition syntax, but production
compilation starts from a source definition. It does not execute the Python
builder and does not compile an already-constructed Python `Morphism`.

## Install

Install the platform wheel for Python 3.12. The wheel contains both the
`catseq` package and the native `catseqc` compiler.

For a source checkout, use uv:

```bash
uv sync --locked --all-extras --dev --python 3.12
```

## Compile a sequence

Save this complete compile-only example as `quickstart_ttl.py`:

```python
from pathlib import Path

from catseq import Compiler
from catseq.hardware.ttl import pulse
from catseq.morphism import Morphism, identity
from catseq.time_utils import ms
from catseq.types import Board, Channel, ChannelType


rwg0 = Board("rwg0")
ttl0 = Channel(rwg0, local_id=0, channel_type=ChannelType.TTL)


class TtlExperiment:
    def build_sequence(self) -> Morphism:
        return identity(0) >> {ttl0: pulse(500 * ms)}


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

`Compiler.from_system()` reads `source_root` and `channels` from the system. A
system may also supply `opaque_calls`, scalar `environment_values`, a target
profile, and an incremental `cache_dir`; these are captured once by the
Rust-owned compiler session. `Compiler.compile()` uses the method only to
locate its source and bind restricted arguments. The method body and reachable
service/module definitions are parsed by the Rust compiler; arbitrary host
lifecycle code is not compiled.

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
