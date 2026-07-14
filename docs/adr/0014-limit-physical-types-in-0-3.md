---
status: accepted
---

# Limit 0.3 physical types to Duration

CatSeq 0.3 gives `Duration` its own base type because integer-cycle timing,
Parallel maxima, Epoch scheduling, and Cycle Quantization require rules that
ordinary floating-point arithmetic cannot express safely.

Frequency, phase, angle, and amplitude remain `Float64` values in 0.3. Their
meaning is supplied by the typed parameter schema of the receiving Atomic
Operation. That schema validates the expected unit convention, permitted range,
Value Availability, and target encoding. These roles do not introduce separate
source-language base types or a general dimensional-analysis system.

This keeps the first native type-analysis milestone focused on scheduling and
does not prevent a later revision from promoting frequently confused physical
roles to nominal quantity types. Such a revision belongs at the Atomic
Operation schema boundary and does not require changing the Morphism arena.
