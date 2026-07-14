---
status: accepted
---

# Use a small source scalar type set

The CatSeq 0.3 restricted source language has the following scalar base types:

- `Unit`, corresponding to Python `None`;
- `Bool`;
- `Int64`, corresponding to Python `int`;
- `Float64`, corresponding to Python `float`;
- `Duration`;
- `String`, restricted to Compile availability.

Target integer widths such as `u8`, `u16`, and `u32` are not source-language
types. An Atomic Operation parameter schema accepts an `Int64`, validates its
target-specific range, and describes its OASM encoding. The same boundary owns
other target representation constraints. This keeps hardware ABI widths out of
ordinary service signatures while preserving checked lowering.

Python arbitrary-precision integer behavior is not part of the restricted
language. Integer literals and constant arithmetic that do not fit `Int64` are
compile errors. `Duration` remains separately represented as a non-negative
integer cycle quantity and is not narrowed through `Int64`.
