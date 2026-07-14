# PROTOTYPE — Arena DAG

Question: can the existing left-folded `>>` composition syntax retain structure
in an integer-indexed arena without recursive traversal, and how does that
compare with the current flat-Lane shape and a nested Python-object DAG?

Run the complete benchmark once:

```bash
uv run python prototypes/arena_dag_throwaway/run.py --all
```

Run the interactive terminal view:

```bash
uv run python prototypes/arena_dag_throwaway/run.py
```

This is deliberately independent throwaway code. It models one serial Lane and
does not import CatSeq, assemble OASM, access USB/network interfaces, or call
`seq.run()`.

The benchmark covers:

- construction, traversal, retained memory, and peak memory;
- recursive versus iterative traversal of a 100,000-atom left-deep chain;
- value-only parameter invalidation;
- timing invalidation from the middle and final 1% of a sequence.

Delete or absorb this directory after the architectural decision is recorded.

Run the real `rb1-next` Rydberg Morphism through pure offline compilation:

```bash
uv run --project ../rb1-next python prototypes/arena_dag_throwaway/real_rydberg.py
```

That command uses the `rb1-next` environment while forcing imports from the
workspace CatSeq checkout. It constructs `assembler(None, nodes)`, does not open
a `BaseExp` context, and never calls `seq.run()`.

Build the same real Rydberg Morphism with the runtime arena replacement, without
running the final CatSeq compiler:

```bash
uv run --project ../rb1-next python prototypes/arena_dag_throwaway/real_rydberg_arena.py --repeats 15
```

The fully lazy prototype records MorphismDef applications, end-state-dependent
batches, and hardware repeats as unexpanded arena nodes. Construction performs
no state query or materialization; the compatibility Lane pass is used only to
verify semantics until the compiler can lower these nodes directly. See
`NOTES.md` for the measurements and remaining one-time builder costs.

Isolate only the arena append/storage cost using the exact real Rydberg node
stream, with a 1 ms pass/fail limit:

```bash
uv run --project ../rb1-next python prototypes/arena_dag_throwaway/isolate_arena_cost.py --repeats 501 --limit-ms 1.0
```

This excludes execution of `build_sequence`, domain object factories, state
queries, calibration I/O, nested compilation, and Lane compatibility views.

Build one symbolic Rydberg template and bind two scan values without mutating
the template:

```bash
uv run --project ../rb1-next python prototypes/arena_dag_throwaway/real_rydberg_scan_binding.py --all --values 0.35 0.55 --fork-repeats 501
```

Run the same command without `--all` for the small interactive binding view.
