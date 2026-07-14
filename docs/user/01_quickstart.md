# CatSeq 0.3 quickstart

CatSeq 0.3 keeps the Python Morphism composition syntax, but production
compilation starts from a source definition. It does not execute the Python
builder and does not compile an already-constructed Python `Morphism`.

## Install

Install the platform wheel for Python 3.12. The wheel contains both the
`catseq` package and the native `catseqc` compiler.

For a source checkout, use uv:

```bash
uv sync --locked --all-extras --dev --python 3.12
```

## Write a sequence

The timing-composition API is unchanged:

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

`@morphism_template` is analogous to a compiled device-function declaration:
its restricted Python body is parsed by `catseqc`, not executed by CPython.
The example is compiled into a shared Serial template containing `set_high`, a
Wait node, and `set_low`; the channel dictionary creates an `Instantiate` node.
Direct CPython execution raises `CompilerOnlyError`.

## Compile a source entry

The host application supplies its channel map (`environment`). CatSeq selects
its packaged, versioned RTMQ target profile automatically:

```python
from catseq.compilation import compile_entry, execute_oasm_calls

result = compile_entry(
    experiment.build_sequence,
    params,
    environment=environment,
)

calls = result.to_oasm_calls(opaque_callables=opaque_callables)
_, exp_sequence = execute_oasm_calls(calls, assembler_seq)
print(result.logical_duration_cycles)
```

`compile_entry()` uses the method only to locate its source and bind restricted
arguments. The method body and reachable service/module definitions are parsed
by `catseqc`; arbitrary host lifecycle code is not compiled.

The old `compile_to_oasm_calls(morphism, ...)` API is removed in 0.3. Native
compiler diagnostics and RTMQ lowering tests now own that behavior.
