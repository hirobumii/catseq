---
status: accepted
---

# Build compile class schemas from static dataclass semantics

The frontend recognizes explicit dataclasses and registered
`typing.dataclass_transform` semantics without executing decorators,
metaclasses, generated initializers, or `__post_init__`. It propagates the
dataclass-like field model through the compile-relevant nominal base and builds
a native `CompileClassSchema` containing fields, class constants, methods, and
properties.

Compile Instances materialize only the complete projection of fields reachable
from a compile entry. Class variables become compile constants. Supported field
defaults, restricted pure default factories, restricted constructor
assignments, and explicit Compile Environment bindings supply native values.
An unreachable host field and its unsupported factory are not evaluated and do
not make the class uncompilable. A reachable field without a native source is a
diagnostic.

One compile-relevant nominal base is supported; purely host-side mixins are
erased. Dynamic MRO behavior, arbitrary descriptors, metaclass execution, and
`__getattr__` are outside the language. Properties are ordinary definitions and
inherit Compile Reachability when read.
