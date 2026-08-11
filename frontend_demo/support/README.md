# Demo support modules

Shared source declarations for frontend demos belong here. Support code is part
of the explicit `frontend_demo` source root. The future actual-object CLI may
import these modules with normal Python semantics, so module top level is
limited to inert resource construction and constants; no Kernel body or host
callback is executed to manufacture compiler facts.
