---
status: accepted
---

# Parse Python with NAC3 parser and AST

The CatSeq production frontend uses a revision-pinned `nac3parser` and
`nac3ast` as its Python syntax layer. Their structured AST replaces the current
tree-sitter traversal for imports, declarations, decorators, annotations,
statements, and expressions. Tree-sitter is removed after the vertical slice
has been migrated; the compiler does not retain two authoritative syntax
trees.

NAC3 AST nodes are normalized immediately into CatSeq-owned Source HIR. NAC3
types, symbol identities, Python-object integration, LLVM values, and code
generation interfaces do not cross that boundary. In particular, CatSeq does
not depend on the LLVM-coupled `nac3core` merely to parse source.

The parser and AST dependency is supplied through a pinned revision or vendored
source with its MIT licensing preserved. The sibling NAC3 checkout under
`exp/` is a persistent design reference, not a production path dependency.
