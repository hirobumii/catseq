---
status: accepted
---

# Expose the compile request through PyO3

The Python `compile_entry()` facade sends the versioned, Python-free Compile
Request directly to a PyO3 extension and receives the encoded Compile Response
in process. The bridge transfers bytes rather than Python AST, Morphism, arena,
or live experiment objects. It releases the GIL and executes compilation on a
Rust thread with the same explicit stack allocation as the standalone
compiler.

The compiler implementation remains a normal Rust library. Both the PyO3
extension and standalone `catseqc` executable are thin adapters over that
library, so process transport is not part of compiler semantics, cache
identity, or diagnostics. `compile_entry()` may still use an explicitly
selected external compiler for diagnostics and compatibility testing, but its
default path is in process.

Platform wheels contain the extension once and install `catseqc` as a console
entry point that invokes the native CLI adapter. Standalone native `catseqc`
archives remain release artifacts for non-Python automation. This avoids
duplicating the complete compiler machine code inside a wheel while retaining
both interfaces.
