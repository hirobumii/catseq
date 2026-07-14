---
status: accepted
---

# Preserve registered dataclass update syntax in 0.3

CatSeq 0.3 temporarily preserves the existing restricted-source spelling for
registered dataclass construction and `dataclasses.replace(...)`. This is a
frontend compatibility choice, not adoption of the Python object model by the
native compiler.

The Rust frontend recognizes a supported `replace(base, field=value, ...)`
call, validates its nominal record schema and field types, and immediately
normalizes it into a complete immutable field vector. Supplied fields directly
replace the corresponding base field expressions; omitted fields are copied
from the base. No `RecordUpdate` overlay or replacement chain survives the
Typed Source HIR normalization boundary, and the compiler never imports the
module, calls Python, or allocates a Python dataclass.

The normalized record is a Contextual Aggregate and must be eliminated before
Morphism arena lowering. When consumed by an Atomic Operation schema, constant
fields become typed payload constants and Link field expressions become target
relocations. The latter is ordinary Runtime Slot binding, not lazy dataclass
replacement. A scan-only update therefore reuses the Morphism DAG and binds
only the affected relocation at RTMQ link time.

This decision does not promise support for arbitrary dataclasses, custom
methods, `__post_init__`, mutation, reflection, dynamic fields, or general
Python `replace` behavior. A later source-language revision may replace this
compatibility syntax with domain-specific Atomic Operation parameters.
