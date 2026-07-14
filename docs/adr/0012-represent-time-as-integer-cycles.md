---
status: accepted
---

# Represent time as integer cycles

CatSeq's canonical Duration representation is a non-negative integer Cycle
Count, not floating-point seconds. A symbolic `DurationExpr` contains integer
constants and Runtime Slots together with checked integer operations such as
addition, subtraction, and maximum; evaluating it always produces a Cycle
Count.

A Logical Timestamp is distinct from a Duration and is represented by
`(EpochId, offset_cycles)`. Adding a Duration to a Logical Timestamp produces a
Logical Timestamp. Subtracting or comparing Logical Timestamps is valid only
within the same Epoch. Sync Phi creates the runtime origin for a later Epoch.

Source unit expressions are converted to Cycle Counts by the frontend, and
time-valued Runtime Bindings are converted before RTMQ linking. CatSeq performs
no implicit rounding: a non-integral cycle quantity is an error unless the
source or scan schema explicitly requests floor, ceiling, or rounding Cycle
Quantization. Decimal unit literals are evaluated exactly before this check so
the result does not depend on binary floating-point behavior.

The compiler uses a sufficiently wide unsigned representation for analysis and
reports overflow. A target with narrower timer fields must validate or split a
Duration during target lowering rather than narrowing silently.
