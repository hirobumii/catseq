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

Do not construct a Python Morphism and pass it to a compiler. Instead, compile
the source entry:

```python
result = compile_entry(
    experiment.build_sequence,
    params,
    environment=environment,
)
calls = result.to_oasm_calls(opaque_callables=opaque_callables)
execute_oasm_calls(calls, assembler_seq)
```

The installed platform wheel contains `catseqc`; callers should use the Python
`compile_entry()` facade rather than locating or invoking the executable
themselves.

Hardware loops are declared as `repeat_morphism(body, count)` or ordinary
compile-reachable Python `for` loops. Loop timing and instruction occupancy are
computed only by native RTMQ lowering.
