---
status: accepted
---

# Use signed Cycle Deltas for Duration

CatSeq represents a source Duration as an exact signed Cycle Delta so a
negative Duration can move the logical time cursor backward within the current
Epoch. Cycle Counts and emitted OASM timestamps remain non-negative: the
compiler rejects an Epoch underflow and physical operations that require an
interval, including pulse and ramp widths, continue to require a non-negative
Cycle Count. Logical `Wait` and channel-local `hold` displacements may be
negative. A rewinding loop is expanded before scheduling because a native
hardware loop cannot represent overlapping iteration timelines. This supersedes
ADR-0012's unsigned Duration representation because rejecting every negative
value prevents intentional timeline overlap, while encoding signed hardware
waits would leak logical scheduling semantics into the target interface.
