---
status: rejected
---

# Use an append-optimized operation vector for Lane

This ADR proposed storing a Lane's operations in a private 32-way persistent
vector with a tail of at most 32 operations. Serial composition would append the
right Lane in order, preserving the current left-folded symbolic duration, while
public access would still return a memoized tuple. This fit the measured Rydberg
operation distribution: 99.3% of same-channel right-hand operands contained at
most 32 operations, and no observed composition joined two operands larger than
64 operations. The proposal was rejected by the acceptance gate below.

## Considered Options

- An AVL rope gives better general large-to-large concatenation but adds binary
  balancing and more nodes for a workload dominated by small right-hand operands.
- A full RRB vector adds efficient arbitrary concatenation and editing that CatSeq
  does not currently need.
- A lazy Morphism expression DAG could defer all normalization but would move the
  seam across widespread direct Lane and state inspection.

## Consequences

Single-operation append is amortized constant time, and concatenation is linear in
the right operand rather than historical Lane length. Tree depth grows logarithmically
with base 32, and operation traversal does not use linear-depth recursion. Large-to-large
concatenation is deliberately not optimized in the first implementation; the private
storage can later deepen into an RRB vector without changing the Lane interface.

CatSeq's composition and compilation modules will not use the public
`lane.operations` tuple on hot paths. They will append, concatenate, inspect
boundary operations, and iterate through Lane's package-internal interface so
intermediate Lanes stay unmaterialized. Only explicit public access to
`lane.operations` creates and memoizes the compatibility tuple.

Symbolic duration structure is part of the compatibility contract. Concatenation
will continue the existing left fold by visiting right-hand operations in order;
it will not combine pre-aggregated left and right Expr values if that would change
parenthesization, even when both forms resolve to the same number.

## Acceptance Gate

Before changing production Lane storage, a throwaway prototype must reduce median
Rydberg `build_sequence` time by at least 15%, improve a 3201-operation single-Lane
build by at least five times with near-linear scaling, and preserve public Lane
behavior, eager errors, symbolic Expr structure, every Rydberg event cost, normalized
OASM calls, and all active-board integer assembly. If it misses the Rydberg threshold,
CatSeq will not adopt the persistent vector and will prioritize expression scanning.

## Prototype Result

The prototype was rejected on 2026-07-12 because it did not improve the real
Rydberg construction workload. It used the proposed 32-way bitmapped vector and
32-operation tail, incremental Lane summaries, internal iteration and
concatenation, lazy memoized tuple access, and runtime-only replacements for the
relevant composition hot paths. No production CatSeq module was modified.

Nine post-warmup real `build_sequence` samples were measured for each version on
the same machine:

- Baseline (ms): 47.966635, 47.401423, 46.520110, 46.519272, 47.017815,
  46.778462, 47.041198, 46.927771, 47.495511; median 47.017815 ms.
- Prototype (ms): 48.532733, 47.917417, 48.712604, 48.647544, 48.091966,
  48.749892, 48.454650, 48.464549, 48.275955; median 48.464549 ms.

The prototype was 3.1% slower, so it missed the required 15% improvement by a
wide margin. The synthetic single-Lane result confirms that the data structure
itself solves long-lane rebuilding, but that workload does not dominate this
Rydberg build:

| Operations | Baseline median | Prototype median | Speedup |
| ---: | ---: | ---: | ---: |
| 201 | 0.519588 ms | 0.101569 ms | 5.12x |
| 401 | 1.768101 ms | 0.191741 ms | 9.22x |
| 801 | 5.971093 ms | 0.386744 ms | 15.44x |
| 1601 | 23.061028 ms | 0.737063 ms | 31.29x |
| 3201 | 88.817519 ms | 1.386194 ms | 64.07x |
| 6401 | 358.363677 ms | 2.767566 ms | 129.49x |

The prototype's log-log scaling slope from 401 through 6401 operations was
0.955, satisfying the near-linear requirement. All non-performance gates also
passed:

- list and tuple construction, input snapshotting, actual memoized tuple access,
  value equality, immutable branching without operand caching, Lane state
  summaries, and eager error timing behaved as designed;
- the left-folded symbolic Expr tree was structurally identical;
- both versions produced 52 lanes, 3016 operations, duration 283075580 cycles,
  561 compiler events, 737 OASM calls, and 10 active assembly boards;
- canonical Morphism shape hash:
  `14bc85d0b61dfb173c5baef64505150917239933b6ca404f7658ee34854bd023`;
- event cost/timestamp/epoch hash:
  `9c3a8217d5a76148a6ce4241dba37b72e1c286b8a7afc2da5db4144d1ffc86ba`;
- normalized OASM call hash:
  `65e5f009833d2f69a5c383fdcb0a280ed904eca7b88a8f46a1895166f623c7f2`;
- integer assembly hash:
  `cb9a13ba5f81f012a255a78732703c6c600929e99369c4213151d080f7bf5f3d`.

The benchmark used only `assembler(None, nodes)` and never called `seq.run()`.
The throwaway prototype was removed after recording these results. CatSeq should
prioritize the already-profiled identity-memoized `contains_expr` optimization
instead of migrating Lane storage now.
