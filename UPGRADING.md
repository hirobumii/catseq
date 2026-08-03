# Upgrading to CatSeq 0.3

CatSeq 0.3 replaces the Python Morphism compiler with the native source
compiler. This is an intentional compiler API break.

## Preserved source API

Morphism construction and composition remain available for simulation,
visualization, and structural tests:

```python
sequence = prepare() >> drive() | monitor()
morphism = experiment.build_sequence(params)
```

## Removed compiler API

The following Python compiler interfaces no longer exist:

- `compile_to_oasm_calls(morphism, ...)`
- `CompilerSession`, `CompileResult`, and `CompileDelta`
- the Python compiler passes and mutable `LogicalEvent` representation
- Python-side OASM precompilation, instruction-cost analysis, and subroutine
  compiler

Do not construct a Python Morphism and pass it to a compiler. In 0.3.2, create
one compiler from the system and compile the source entry:

```python
compiler = Compiler.from_system(system)
runtime = EthernetRuntime(
    interface=runtime_interface,
    destination=chassis_destination,
    reply=reply_endpoint,
    boards=board_routes,
)

compiled = compiler.compile(experiment.build_sequence, params)
success = runtime.run(compiled)
```

`CompiledSequence` and the compiler/runtime configuration values are owned by
Rust and exposed through PyO3. OASM instruction encoding remains private and
has no device side effects; only `EthernetRuntime.run()` opens the Ethernet
transport.

The 0.3.1 `compile_entry()`, `assemble_oasm_calls()`, and
`execute_oasm_program()` helpers are no longer public exports. Experiment code
should not construct `LinuxRawEthernetRuntimeConfig`, `BoardEndpoint`, an OASM
assembler, or a hand-written per-sequence Compile Environment.

The installed platform wheel contains `catseqc`; callers should use the Python
`Compiler` facade rather than locating or invoking the executable themselves.

Hardware loops are declared as `repeat_morphism(body, count)` or ordinary
compile-reachable Python `for` loops. Loop timing and instruction occupancy are
computed only by native RTMQ lowering.
