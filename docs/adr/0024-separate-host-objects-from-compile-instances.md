---
status: accepted
---

# Separate host objects from compile instances

A Python class may contain both host definitions and CatSeq compile
definitions. Only explicit compile entries, such as `@arena_build` methods, are
roots. Resolved service/module methods, helpers, property getters, and required
restricted constructors inherit Compile Reachability transitively and require
no additional decorator. Other definitions on the same class remain host code.

CPython may construct a Host Object and execute its metaclass, generated
initializer, `__post_init__`, device setup, persistence, and analysis behavior.
The binary compiler never imports or inspects that live object. It builds a
separate immutable Compile Instance from statically declared fields, supported
restricted expressions, and explicit Compile Environment bindings. The result
has a stable `InstanceId` and a complete native projection of compile-reachable
fields. Unreachable host fields and their initializers are not materialized.

A compile-reachable field read must have a native value derivable from those
inputs. A value created only by host lifecycle code is unavailable to compiled
methods. Reaching an unsupported host method or property is a compile error at
the relevant Definition DAG edge, not permission to execute Python.
