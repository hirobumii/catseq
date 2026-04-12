# CatSeq V2 Upgrade Plan

## Goal

Upgrade CatSeq around three core IRs:

1. `Expr` for values and runtime data
2. `Morphism` for global static hardware-action regions
3. `Program` for global AST-first runtime/feed-forward control

The source model stays global. Board structure and physical partitioning remain compiler concerns.

## Current Direction

- `Morphism` remains the static semantic center for deterministic experiment regions.
- `Program` is added as a separate IR, not merged into `Morphism`.
- `Program` embeds static regions with `Emit(morphism)`.
- The compiler is allowed to inspect concrete channel metadata carried by user-facing channel handles, but normal user code should treat those handles opaquely.
- Concrete-only normalization and validation happen only in the realization pipeline.

## Architecture

### `Expr`

- Represents constants, symbolic values, runtime values, arithmetic, comparisons, and later measurement-derived data.
- Serves both `Morphism` payload/state realization and future `Program` control flow.

### `Morphism`

- Represents global static experiment structure.
- Keeps algebraic composition with `>>` and `|`.
- Uses trigger-wait semantics:
  - non-wait primitives are algebraically instantaneous
  - only `wait` / `identity()` contributes duration
- Internally uses a private arena-backed DAG with iterative passes.
- Lowers to lane/compiler form only after realization.

### `Program`

- Represents global runtime/feed-forward logic.
- Must be AST-first, not callback- or generator-based.
- Must stay separate from `Morphism` so control flow does not break morphism algebra.
- Embeds static regions via `Emit(morphism)`.

Recommended minimal node set:

- `Seq`
- `Emit`
- `Measure`
- `Let`
- `Branch`
- `Repeat`
- `While`
- `FunctionDef`
- `Call`
- `Return`
- `Select`

### Compiler Boundary

- User-facing channel handles may already contain concrete `board`, `local_id`, and `channel_type` metadata supplied by experiment-side wrappers.
- Users should be able to write against handles like `mot_laser` without manually reasoning about board placement in normal use.
- The compiler may inspect the embedded physical metadata directly.
- CatSeq does not need a separate abstract-vs-physical channel split as long as handles are opaque in use and physically informative to the compiler.

## Realization Pipeline

### Construction

- Allow symbolic state and symbolic parameters.
- Constructors enforce only structural invariants valid for both symbolic and concrete values.

### Realization

- Resolve symbolic expressions against bound input state.
- Canonicalize concrete data.
- Run delayed validations.
- Produce realized state/parameter objects.

Concrete-only logic belongs here:

- sorting waveform snapshots / pending waveforms
- waveform-count checks
- `fct` compatibility checks
- checks that require concrete values
- concrete transition legality checks

### Lowering

- Lower realized `Morphism` and future `Program` regions into compiler-ready representations.
- Keep lanes and board-local schedules as lowered artifacts, not public semantic objects.

## Compiler Roadmap

1. Keep v1 compiler stable except for bug fixes and compatibility work.
2. Replace the current v2-to-v1 fallback gradually with direct v2 lowering.
3. Define one clean lowering sequence:
   - global source IR
   - normalization
   - realization
   - physical-channel-aware compilation
   - partition into per-board RTMQ/OASM artifacts
4. Preserve the fact that pure static morphisms can compile into per-board schedules after initial synchronization.
5. Extend compilation later for runtime/feed-forward `Program` regions.

## QEC / Feed-Forward Direction

- Treat measurement/decoding as boundaries between static morphism regions.
- Use `Program` to express:
  - measurement
  - decoding
  - branching
  - looping
  - selection of precompiled correction regions
  - realtime functions/subroutines
- Prefer runtime selection among precompiled morphism families over arbitrary runtime morphism synthesis.

Example shape:

1. `Emit(stabilizer_round)`
2. `Measure(ancilla_ro, raw)`
3. `Call(decode_fn, [raw], syn)`
4. `Emit(Select(correction_table, syn))`
5. `Repeat` / `While` for repeated QEC rounds

## Implementation Order

1. Stabilize `v2` `Expr` / `Morphism` / realization as the semantic core.
2. Add `catseq/v2/program.py` with the minimal AST-first `Program`.
3. Add one end-to-end feed-forward example using `Emit`, `Measure`, `Call`, and `Select`.
4. Define direct lowering from v2 IRs into compiler input.
5. Gradually migrate helper/compiler entrypoints from v1 fallback to direct v2 lowering.

## Rules

- No board structure in the user-facing source model.
- No physics-semantic resource layer inside CatSeq core.
- No control-flow nodes inside `Morphism`.
- No concrete-only validation during symbolic construction.
- Keep one canonical repo plan in this file.

