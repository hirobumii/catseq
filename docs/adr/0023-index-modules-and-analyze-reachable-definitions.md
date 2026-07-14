---
status: accepted
---

# Index modules and analyze reachable definitions

The frontend parses each loaded Source Module once into a NAC3 AST and builds a
module-level declaration index before analyzing any body. The index records
imports, classes, functions, properties, signatures, decorators, and stable
`DefinitionId`s. It does not apply CatSeq semantics to every function in the
file.

Starting from the requested entry, the compiler lowers function, property, and
constructor bodies to Source HIR only when a resolved use makes that definition
reachable. Unreachable host definitions need only be syntactically valid
Python. Reachable mutually recursive definitions form a strongly connected
component and are constraint-generated and unified together.

Compile Reachability classifies definitions, not classes. An explicit compile
entry is a root; resolved service methods, module methods, property getters, and
restricted constructors become compiled only when reached from a root. Other
methods on those same classes remain host definitions. A reachable definition
that cannot satisfy the restricted language is an error rather than a reason to
compile or execute its surrounding class as Python.

Incremental caches attach normalized body digests, name-resolution inputs, and
typed artifacts to `DefinitionId`s. A source edit invalidates the changed
definition and transitive Definition DAG users without treating the entire
file or entry program as the compilation unit.
