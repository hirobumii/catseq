# AGENT.md

This file records the standing development rules for future Codex sessions in this repository.

## Session Start

- Read relevant Serena memories before making architectural decisions.
- At minimum, check these memories when working on `v2`:
  - `project_overview`
  - `style_and_conventions`
  - `suggested_commands`
  - `morphism/package-layout`
  - `morphism/v2-upgrade-plan`
  - `morphism/v2-implementation-status`
- Treat Serena memories as part of the working context for this repo, not optional background.

## Tooling And Commands

- Use `uv`, not bare `python`, `pytest`, `ruff`, or `mypy`.
- Preferred command style:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --python .venv/bin/python pytest -q`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --python .venv/bin/python ruff check catseq tests`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run --python .venv/bin/python mypy catseq`
- The repo target is Python `3.12+`.
- Prefer `uv venv --python 3.12` and `uv pip install -e .[dev]` for environment setup.

## Typing Rules

- Use Python 3.12 typing style.
- Use built-in generics like `list[T]`, `dict[K, V]`, `tuple[T, ...]`.
- Use `X | Y` instead of `Optional[X]` or `Union[X, Y]` where possible.
- Prefer `type` aliases over older alias patterns when defining shared type aliases.
- Do not use outdated quoted annotations like `"Expr"` when normal annotations work.
- Use `from __future__ import annotations` where appropriate instead of stringified type hints.
- Do not introduce `Any`.
- Do not use `object` as a lazy catch-all type hint.
- If a type is not yet modeled precisely, define or refine a real domain type instead of falling back to `Any` or `object`.
- Keep type surfaces explicit at subsystem boundaries.

## V2 Architecture

`v2` is still under development. Internal coherence is more important than preserving unstable convenience imports.

Core direction:

- `Expr`, `Morphism`, and `Program` are separate IR layers.
- `Morphism` is for static deterministic experiment structure.
- `Program` is for runtime / feed-forward / measurement-driven control flow.
- `Program` uses `Emit(morphism)` as the bridge to static regions.
- Do not merge control-flow nodes into `Morphism`.
- Do not leak `Program` runtime concerns into the public static `Morphism` API unless there is a very strong reason.
- Keep the source model global. Board ownership and placement are compiler concerns.
- Keep channel handles opaque in user code even if they carry concrete physical metadata internally.

## V2 Package Organization

- Do not build `v2` as a flat folder.
- Prefer package organization by subsystem, following the `v1` style.
- Current expected direction:
  - `catseq/v2/expr/`
  - `catseq/v2/morphism/`
  - `catseq/v2/program/`
  - `catseq/v2/hardware/`
- Hardware-specific helpers such as TTL, RWG, and future hardware families belong under `catseq/v2/hardware/`.
- New hardware support should be added as new modules/packages under `catseq/v2/hardware/`, not at the top level of `catseq/v2/`.
- Keep `catseq/v2/__init__.py` slim. Re-export only the truly central surface.
- Since `v2` is unstable, it is acceptable to change internal and import structure to improve architecture.

## V2 Semantic Rules

- Realization is the boundary for concrete normalization and delayed validation.
- Do not perform concrete-only validation during symbolic construction.
- Keep `Program` AST-first. Do not start with a Python-subset compiler front-end.
- Runtime-valued `Emit` is allowed inside `Program`, but experiment-specific algorithms do not belong in CatSeq core.
- Experiment-specific planning logic should live in tests, examples, or experiment repos unless it is clearly a reusable core abstraction.
- Keep `v1` compiler behavior stable except for targeted fixes.
- `v2` may still lower through legacy paths temporarily, but the long-term direction is direct `v2` lowering.

## Testing And Validation

- Use `pytest`.
- Prefer targeted tests first, then the full suite if core code was changed.
- When adding a new abstraction to `v2`, add tests that check expressibility and semantics, not only smoke behavior.
- Differential or reference-style tests are good for experiment-inspired logic, but experiment-specific reference code should stay in `tests/` unless it truly belongs in core.

## Refactoring Guidance

- Favor package boundaries and small modules over large flat files.
- Preserve stable public APIs in mature `v1` areas when refactoring.
- In `v2`, prefer architectural cleanup over temporary compatibility shims.
- If a new file starts combining AST definitions, value containers, lowering, execution, and experiment logic, split it.
- If behavior is hardware-specific, put it under the hardware namespace.
- If behavior is experiment-specific, do not place it in CatSeq core by default.
