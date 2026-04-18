# Upgrading to 0.2.3

## Summary

`0.2.3` introduces three related changes on `main`:

- a fresh top-level `catseq.expr` package for source-level symbolic expressions
- a cleaner source time model where hardware atomic ops are logically instantaneous
- a real opaque timed-region primitive for blackbox-style execution regions

The legacy compiler path remains concrete-only. If a morphism contains unresolved exprs, it must be realized before compilation.

## What changed

### Source time model

Source logical time now treats ordinary hardware ops as point-like:

- TTL init/on/off: instantaneous
- RWG init/load/play/rf switch: instantaneous
- sync markers: instantaneous
- only explicit delays (`identity`, `hold`) advance source logical time

Practical effect:

- `ttl_on >> blackbox >> ttl_off` now has source logical duration equal to the blackbox region duration
- old code that relied on implicit extra source cycles from atomic ops may observe different `total_duration_cycles`

### Expr system

New public API:

- `catseq.expr.Expr`
- `catseq.expr.var(...)`
- `catseq.expr.input_state()`
- `catseq.expr.resolve_value(...)`
- `catseq.expr.realize_morphism(...)`

Exprs are allowed in source morphism construction, including:

- durations
- RWG carrier frequency
- RWG waveform/ramp scalar fields

Compile-time-resolved float exprs are supported in RWG value positions.

### Timed regions / blackbox

Blackbox-style opaque execution regions are now modeled as timed regions rather than long fake atomic ops.

Current blackbox time semantics is:

- interval model `(a, b]`
- same-board point events at the start boundary `a` are allowed
- same-board point events with `a < t <= b` are rejected

This matches the current source-time interpretation for instantaneous atomic ops plus duration-bearing opaque regions.

## Required caller changes

### If you stay fully concrete

Most current experiments do not need source changes.

Existing concrete code like current `Rb1-rtmq` sequence construction continues to work. The real `RamanTransferExp.build_sequence()` was recompiled successfully against this version.

### If you start using exprs

Before compiling with the legacy compiler, realize first:

```python
from catseq.expr import realize_morphism
from catseq.compilation.compiler import compile_to_oasm_calls

realized = realize_morphism(morphism, env={"t": 10, "freq": 12.5})
calls = compile_to_oasm_calls(realized, assembler_seq)
```

If unresolved exprs remain, `compile_to_oasm_calls(...)` now raises a targeted error.

## Notes for blackbox / repeat_morphism users

- `repeat_morphism(...)` and related opaque region helpers still produce concrete timed regions
- callers remain responsible for the declared duration/state contract of those opaque regions
- immediate same-board point events that land inside a timed region are still illegal

## Verification baseline

Repo-wide verification for this release:

- `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`
- result: `136 passed`
