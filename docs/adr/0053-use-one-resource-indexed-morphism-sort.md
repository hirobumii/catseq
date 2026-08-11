---
status: accepted
---

# Use one resource-indexed Morphism sort across slot binding

CatSeq uses one `Morphism` sort before and after Resource Slot Binding. A
Morphism is indexed by a finite Resource Context of formal slots; binding is
substitution of compatible logical resources for those slots and does not turn
a `MorphismTemplate`, `MorphismFamily`, or `MorphismDef` value into a different
kind of object. A Morphism Definition is the restricted source declaration that
produces such values, not their type.

This corresponds schematically to
`Morphism[Delta; Requires => Provides]`, where the Boundary Contract contains
local facts indexed by Resource Slots rather than a whole-machine environment.
Binding removes entries from `Delta` while substituting their logical resource
identities through that contract. Resource closure and boundary/context closure
are independent compiler facts. The Selected Compile Entry must have both an
empty `Delta` and an empty external `Requires` set before target lowering.

## Considered options

- A distinct `MorphismTemplate` or `MorphismFamily` value type was rejected
  because resource binding does not change the sequencing algebra.
- `ReaderMorphism` was rejected because Reader is one possible functional
  encoding of the resource parameter, not a CatSeq domain concept.
- `OpenMorphism` was rejected because it conflates free Resource Slots with
  unsatisfied boundary requirements.

## Consequences

The existing `MorphismDef`, `MorphismTemplate`, `Instantiate`, and decorator
spellings may remain temporarily as compatibility or representation details,
but they cannot define a second semantic sort. Their source/API migration is
follow-up implementation work. ADR 0007 is superseded.
