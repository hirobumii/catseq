---
status: accepted
---

# Qualify types by Value Availability

Every Typed Source HIR value has a base type and a Value Availability. `Compile`
values are known during specialization, `Link` values are populated from Link
Bindings before RTMQ linking, and `Device` values exist only while the hardware
program executes. Link Bindings include Runtime Slots for scans and Environment
Slots for Compile-known but deliberately relocatable external scalars. This
qualifier is part of one type analysis and does not prescribe separate compiler
invocations.

Expression availability is the latest availability of its inputs. DAG topology,
call targets, channel selection, and structural control flow require Compile
availability. Supported RTMQ timing and numeric operands may use Link
availability. CatSeq 0.3 does not permit a Link or Device value to control a
source `if`; Device values are limited to target-declared operand positions.
Future hardware branching would require runtime timing to reconverge through
Sync Phi.

The compiler does not create parallel families such as `RuntimeFloat` and
`RuntimeDuration`. A scan-derived duration is `Duration @ Link`, while a
constant duration is `Duration @ Compile`. Base-type rules and availability
rules remain independently testable and extensible.

Availability records the earliest time a value is known; it does not require a
Compile-known value to be baked into an artifact. A separate Dependency Role
marks uses as Structural or Relocatable. A Compile Environment scalar used only
as a supported numeric operand or duration may be emitted as an Environment
Slot and bound at link, while a topology-affecting use enters specialization.
