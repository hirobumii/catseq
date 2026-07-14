---
status: accepted
---

# Relocate nonstructural environment values at link

Value Availability states when a value first becomes known; a separate
Dependency Role states whether using it changes compilation structure. Compile-
known values used for control flow, call or channel selection, hardware
topology, or another structural decision enter the Specialization Key and Query
DAG dependencies.

A Compile Environment scalar used only as a supported duration or Atomic
Operation operand is instead represented by an `EnvironmentSlot` in the native
Value Expression Arena. Runtime scan inputs remain distinct Runtime Slots. Link
Bindings supply both sources before Rust RTMQ linking evaluates expressions,
checks Atomic schemas, schedules relative offsets, relocates boards, and emits
the OASM Call Plan.

Consequently, changing a topology-independent calibration or immutable instance
scalar relinks an existing Morphism and relative RTMQ artifact. Changing a
structural value respecializes the affected definition and its actual Query DAG
consumers. A value used in both roles participates in both mechanisms.
