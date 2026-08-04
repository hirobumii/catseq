# Upgrading CatSeq

## 0.4.0 to 0.4.1: make every hardware duration explicit

CatSeq 0.4.1 no longer interprets a bare `int` or `float` passed to a hardware
timing parameter as a target Cycle Count. Use an SI unit when the source value
is a physical time, or `cycles(...)` when it is deliberately target-relative:

```python
from catseq.hardware.ttl import pulse
from catseq.time_utils import Duration, cycles, ms


def exposure(duration: Duration):
    return pulse(duration)


physical = exposure(500 * ms)
target_relative = exposure(cycles(125_000_000))
```

This rule is checked after values flow through local variables, module globals,
user functions, annotated Environment Slots, and scan bindings. It also applies
to `identity`, apart from the neutral `identity(0)` spelling. Annotating
`duration: float` no longer makes
it compatible with `pulse`, `hold`, `rf_pulse`, or `linear_ramp`; annotate it as
`Duration`. A module constant such as `DELAY: Duration = 0.5` is still invalid
because the annotation does not supply a unit.

Conversion uses the selected target profile's `clock_hz`. The built-in RTMQ
profile uses strict quantization, so a value such as `15 * ns` at 100 MHz is an
error rather than an implicitly rounded duration. Host-side conversion helpers
also require the clock explicitly:

```python
from catseq.time_utils import time_to_cycles

cycle_count = time_to_cycles(0.5, clock_hz=compiled.clock_hz)
```

`Duration` is a signed logical displacement in 0.4.1. For example,
`identity(-1 * us)` moves the following source operation one microsecond back
within the current Epoch; it does not emit a negative hardware wait. The
compiler rejects movement before the Epoch origin. Pulse and ramp widths remain
non-negative; rewinding loop bodies are expanded before scheduling rather than
encoded as native hardware loops. `CompiledSequence.logical_duration_cycles`
remains the non-negative furthest logical timestamp reached by the sequence.

Remove imports of `CLOCK_FREQ_HZ`, `CYCLE_DURATION_S`, `CYCLES_PER_US`, or
`mu`; those implicit 250 MHz aliases are no longer public. The zero-duration
`identity(0)` spelling remains the neutral sequencing morphism and does not
define the unit contract of hardware timing parameters.

When multiple TTL transitions target the same channel and logical cycle,
0.4.1 applies them in source order and emits the final state. Code must not
depend on the previous high-wins merge accident.

## Upgrading to CatSeq 0.3

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
