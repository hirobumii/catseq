---
status: accepted
---

# Use one type signature per source definition

Each CatSeq 0.3 source Definition Revision has exactly one inferred Type
Signature. The restricted source language has no user-defined generic functions
and does not monomorphize a definition by base type or Value Availability. Calls
that would require one source helper to have incompatible signatures are type
errors.

Native polymorphism remains available through the Intrinsic Registry. Type
inference resolves an overloaded scalar operation, replacement operation, or
Atomic Schema to one concrete intrinsic identity before specialization.
Morphism Template parameters are value- and handle-level bindings rather than
source-language type parameters.

A definition may still have multiple Specialization Keys. They differ only in
values and identities used Structurally: structural arguments, Compile Instance,
Channel and Board bindings, relevant Compile Environment facts, intrinsic
schema versions, and dependency revisions. Link Bindings, Value Availability,
and Compile scalars used only as relocatable atomic operands are excluded.

The Type Signature fingerprint contributes through the Definition Revision's
interface identity instead of forming another specialization axis. An
availability-polymorphic body uses its Availability Transfer and symbolic Value
Expression parameters; passing a constant rather than a Runtime Slot does not
by itself create a new template specialization.
