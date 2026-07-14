---
status: accepted
---

# Register nominal hardware State Types

The Rust compiler does not hard-code one closed enum containing every TTL, RWG,
RSP, or future hardware state. Each accepted hardware-state definition receives
a stable `StateTypeId` and is associated with a stable `ChannelKindId` in a
nominal registry.

Concrete definitions such as `RWGReady`, `RWGActive`, and `RSPPIDActive` remain
distinct nominal State Types even when their fields happen to match. Enum-like
states such as TTL states retain one nominal type with compiler-known variants.
Atomic transition schemas constrain their incoming and outgoing State Type and
may refer to typed state fields.

State Types appear in Morphism Effects and internal State Environments. They are
not source-language state maps or explicit service arguments. The restricted
frontend discovers accepted state definitions and validates their fields; the
target backend separately registers the operation lowering that consumes them.

This permits new hardware families and states without editing a central Rust
enum while preserving nominal transition safety and stable incremental
dependency identities.
