---
status: accepted
---

# Resolve imports without Python execution

The CatSeq binary compiler resolves restricted Python imports through a static
Source Bundle rather than CPython's import machinery. Explicit project source
roots locate Source Modules; a Rust registry supplies Intrinsic Modules; and
imports used only by host code remain unloaded. Reachable dynamic imports,
import hooks, wildcard imports, and runtime `sys.path` changes are errors.

Each loaded module first publishes its imports, declarations, and stable
definition identities. A static Symbol Resolver then follows symbols actually
referenced by the reachable definition worklist. This preserves NAC3's useful
separation between top-level definition registration, symbol resolution, and
unified type analysis while deliberately replacing NAC3-ARTIQ's live
`PyModule` and Python-object-ID integration.

Import edges resolve names; Definition DAG edges record actual semantic use.
Incremental invalidation therefore propagates through referenced definitions
rather than invalidating every importer of a changed file. Package initializers
are never executed and are read only when their static exports are required.
