# CatSeq compilation and execution API redesign

Document class: current design

Status: 0.4.0 compiler/runtime and `catseq.experiment` integration implemented;
full Rydberg hardware acceptance remains pending

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
| Experiment lifecycle | `catseq.experiment.base_exp.BaseExp` | CatSeq Python framework using supplied collaborators |

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

`catseq.experiment.base_exp.BaseExp` composes the two low-level modules without
exposing their setup to an experiment subclass. The first point compiles
synchronously; after device parameters are applied, point N+1 starts compiling
before the runtime executes point N:

```text
record attempted ScanPoint
  -> take prefetched CompiledSequence, waiting if needed
     (compile synchronously for the first point)
  -> apply device parameters and initialize devices
  -> start compiling the next immutable ScanPoint
  -> runtime.run(compiled)
  -> read devices and run streaming analysis
```

Experiment subclasses continue to define `build_sequence(params)`. They do not
construct assemblers, interfaces, Compile Environments, or board endpoints.
One `BaseExp` instance owns the complete scan and execution lifecycle; CatSeq
does not add a separate `ExperimentRun` wrapper. A speculative next-point
compilation is not an attempted execution and is recorded in `ParaDict` only
when normal Descartes traversal reaches it.

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
4. [x] Prove the low-level external TTL compiler/runtime path without public
   OASM symbols or a hand-written Compile Environment.
5. [x] Execute the accepted
   [`catseq.experiment` migration plan](catseq_experiment_migration_plan.md),
   migrate the first RB1 consumers, and verify the BaseExp TTL tracer.

## Acceptance benchmark

The completed external TTL benchmark is the `catseq.experiment` tracer bullet.
Its source contains a normal CatSeq TTL sequence, imports `BaseExp` from
`catseq.experiment.base_exp`, and imports `BaseModule` and `BaseService` from
`catseq.experiment.base_module`. It does not mention `SimpleNamespace`,
`assembler`, `run_cfg`, OASM core types, `BoardEndpoint`, instruction capacity,
schema version, a raw environment dictionary, or `rb1system.abstract`.
Compilation produced the expected 500 ms call plan, the physical run returned
successful evidence for `rwg0`, and the lifecycle produced a readable H5
record. Exact evidence is retained in the migration plan; the full Rydberg
experiment remains the next downstream hardware gate.

## Verification checkpoints

The low-level Compiler/Ethernet Runtime path was verified on 2026-08-02 with
the external single-file TTL benchmark. The compiler emitted the expected 500
ms plan, and the physical runtime returned successful terminal evidence for its
configured board. The BaseExp-level TTL tracer then passed on 2026-08-03; the
selected Rydberg run remains open in Phase 7 of the migration plan.

An offline differential regression test also verifies that the private explicit
reply-endpoint adapter produces the same finalized OASM instruction words and
exception-handler position as the former context-attached endpoint path.
