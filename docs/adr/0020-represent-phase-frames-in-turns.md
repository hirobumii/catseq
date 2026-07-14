---
status: accepted
---

# Represent phase frames in turns

CatSeq represents a Phase Frame as `Float64` turns: `0.0` corresponds to zero
phase and `1.0` corresponds to `2π`. Frame updates use Euclidean modulo one and
therefore normalize finite values to `[0.0, 1.0)`. This matches the existing
OASM RWG API and the established microwave code's modulo-one convention.

Rotation angles expressed in radians remain ordinary `Float64` values with a
distinct Atomic Operation parameter role; they are not Phase Frame values.
Target phase words, including the RWG 20-bit representation, are quantized only
during target lowering because their precision is hardware-specific and does
not affect Morphism topology or timing. Link-time scan phase expressions carry
native modulo-one normalization in the Value Expression Arena.
