# CatSeq compilation and execution API redesign

Status: 0.3.2 implementation complete; BaseExp migration remains downstream

## Goal

Expose the experiment concepts that remain useful after the Rust compiler and
runtime migrations, while hiding the Python-native compromises of OASM. The
normal API has one system-scoped Compiler, immutable Compiled Sequences, and a
reusable Ethernet Runtime.

## Public workflow

```python
compiler = Compiler.from_system(system)

runtime = EthernetRuntime(
    interface=runtime_interface,
    destination=chassis_destination,
    reply=reply_endpoint,
    boards=board_routes,
)

compiled = compiler.compile(exp.build_sequence, params)
result = runtime.run(compiled)
```

The example is the intended common-case surface, not the internal PyO3
constructor schema. Schema versions, instruction capacities, OASM core objects,
and platform transport implementation names are not ordinary experiment
arguments. A run timeout is derived from the Compiled Sequence duration plus a
runtime margin, with an explicit override reserved for exceptional cases.

## Ownership

| Concept | Public owner | Authoritative implementation |
| --- | --- | --- |
| Compile Environment | Compiler setup | Rust, exposed through PyO3 |
| Incremental compilation state | Compiler | Rust compiler queries and cache |
| OASM Call Plan and logical duration | Compiled Sequence | Rust, exposed through PyO3 |
| RTMQ instruction encoding | none | private Python OASM adapter |
| Physical board routes and reply endpoint | Ethernet Runtime | Rust, exposed through PyO3 |
| RTLink, Ethernet transport, monitoring | Ethernet Runtime | Rust runtime |
| Experiment lifecycle | BaseExp | Python framework using Compiler and Runtime |

Python locates the bound source entry and invokes the pinned OASM encoder. It
does not duplicate runtime schemas, schedule calls, validate topology, or send
network frames.

## Compiler and runtime boundary

```text
restricted Python sequence source
  -> Compiler
  -> immutable Compiled Sequence
       - OASM Call Plan
       - logical duration
       - diagnostics
  -> Ethernet Runtime.run(compiled)
  -> private OASM encoder
  -> Rust-owned AssembledOASMProgram
  -> Rust runtime and Ethernet transport
  -> structured execution result
```

The Compile Environment contains source-external compilation facts such as
channel mappings, calibration snapshots, and intrinsic bindings. Compiler or
system setup constructs it once. Physical interface, chassis address, reply
endpoint, and board-node routes belong only to the Ethernet Runtime.

At the Python boundary, `system.channels` maps fully qualified source names to
typed CatSeq channels, `system.opaque_calls` optionally maps opaque operation
names to their host encoder callables, and `system.environment_values`
optionally supplies scalar Environment Slot values. The facade converts these
objects once; callers do not construct schema-versioned dictionaries.

## Preserve and replace

| Existing concept | Decision |
| --- | --- |
| `build_sequence(params)` | Preserve as the experiment sequence entry |
| Explicit compile and run stages | Preserve |
| Logical board addresses and physical routes | Preserve with typed ownership |
| Compile duration, diagnostics, and execution evidence | Preserve |
| `compile_to_oasm_calls(morphism, seq)` | Replace with `Compiler.compile(entry, params)` |
| `eth_intf` and mutable `nod_adr` / `loc_chn` | Replace with Ethernet Runtime construction |
| `run_cfg` | Remove from the public API |
| `assembler`, `C_MAIN`, `C_RWG`, and `C_RSP` | Keep only inside the private encoder |
| `seq.asm` and `seq("main", callback)` | Remove |
| OASM `seq.run()` and pcap communication | Replace with `EthernetRuntime.run(compiled)` |
| Hand-written per-call `environment` dictionary | Move to Compiler/system setup |
| Public `LinuxRawEthernetRuntimeConfig` construction | Replace with Ethernet Runtime |

## BaseExp integration

BaseExp composes the two low-level services without exposing their setup to an
experiment subclass:

```python
class BaseExp:
    compiler: Compiler
    runtime: Runtime

    def compile(self, params):
        return self.compiler.compile(self.build_sequence, params)

    def execute(self, params):
        compiled = self.compile(params)
        return self.runtime.run(compiled)
```

Experiment subclasses continue to define `build_sequence(params)`. They do not
construct assemblers, interfaces, Compile Environments, or board endpoints.

## Failure boundaries

- A compile failure produces no Compiled Sequence.
- OASM encoding and complete topology validation finish before network I/O.
- An encoding failure cannot dispatch a partial program.
- Runtime failures retain dispatch certainty, per-board evidence, and device
  exception details.
- No previous Compiled Sequence is installed implicitly after a failed compile.

## Compatibility and non-goals

- OASM remains the instruction encoder until a native RTMQ encoder is built,
  but its object model is not a public compatibility target.
- This redesign does not add a native RTMQ encoder.
- `EthernetRuntime` does not expose Linux raw sockets in its public identity;
  platform adapters remain internal.
- The accepted 0.3 compiler and runtime ownership boundaries remain intact.

## Implementation sequence

1. [x] Add Rust-owned Compiled Sequence and system-scoped compile configuration to
   the PyO3 surface.
2. [x] Add the thin Compiler facade and move OASM assembly behind an internal
   encoder module.
3. [x] Add Ethernet Runtime as the public execution facade over the existing Rust
   runtime contract.
4. [x] Convert the external TTL benchmark so it imports no OASM symbols and passes
   no hand-written Compile Environment.
5. [ ] Port BaseExp to compose Compiler and Runtime, then migrate experiments one
   at a time.

## Acceptance benchmark

The external TTL benchmark is the tracer bullet. Its source must contain a
normal CatSeq TTL sequence and the short public setup shown above. It must not
mention `SimpleNamespace`, `assembler`, `run_cfg`, OASM core types,
`BoardEndpoint`, instruction capacity, schema version, or a raw environment
dictionary. Compilation must produce the expected 500 ms call plan, and the
physical run must return successful evidence for `rwg0`.

## 0.3.2 verification checkpoint

Verified on 2026-08-02 with the external single-file TTL benchmark. The
compiler emitted the expected 500 ms plan, and the physical runtime returned
successful terminal evidence for its configured board. Concrete interface,
chassis, reply, and board-route values remain in the external hardware test.

An offline differential regression test also verifies that the private explicit
reply-endpoint adapter produces the same finalized OASM instruction words and
exception-handler position as the former context-attached endpoint path.
