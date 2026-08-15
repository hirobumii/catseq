# CatSeq Compiler Domain

CatSeq separates pure realtime value computation from hardware timing and
structured control while preserving explicit interfaces between those domains.

## Compute language

**Compute Profile**:
The source-language meanings accepted for pure realtime value computation,
distinct from Morphism timing and Control topology.

**Compile-known Computation**:
A source computation completed during frontend specialization before any
Compute unit is formed. It follows host Python semantics and is outside the
Compute Profile.
_Avoid_: Realtime computation, Device computation

**Compute Integer**:
The signed 32-bit scalar denoted by canonical Python `int` or its explicit
`int32` synonym within the initial Compute Profile. Arithmetic wraps at 32
bits, while an out-of-range source literal is invalid.
_Avoid_: Host integer, Int64

**RTMQ Division Primitive**:
The target operation that loads two 32-bit operands into `OP0` and `OP1`, then
writes either `OP0 div OP1` or `OP0 mod OP1` to a 32-bit TCS entry after the
target-specific divider latency. Divider availability and signedness are target
properties. Current QCtrl Master, RWG, and RSP nodes enable an unsigned divider,
so this primitive is not by itself the signed Python `//` or `%` operation.
_Avoid_: Python division, Compute division

**Compute Integer Division**:
The required signed Int32 `//` and `%` operations in the initial Compute
Profile. They have Python floor-quotient and divisor-signed-remainder semantics;
the compiler must lower those semantics over the current unsigned RTMQ division
primitive. A divisor proven to be zero is a compile-time error at its source;
otherwise a Device-time zero divisor traps at runtime without a default result
or fallback path. Fixed-point division is deferred, and integer `/` remains
outside the profile because Python defines it to produce a floating-point
result. The sole unrepresentable Int32 quotient, `INT_MIN // -1`, wraps to
`INT_MIN`; its remainder is zero.
_Avoid_: Unsigned target division

**Compute Semantic Operation**:
A target-independent typed operation retained intact through the Compute
frontend. Signed Int32 floor division and modulo remain such operations rather
than being expanded into unsigned arithmetic during source analysis. Target
lowering later selects RTMQ instructions, adds sign correction, accounts for
divider latency, and claims the divider resource.
_Avoid_: RTMQ instruction sequence, eagerly expanded arithmetic

**Compute Shift**:
The fixed-width signed Int32 `<<` and `>>` operations. For a non-negative shift
count greater than or equal to 32, left shift yields zero and arithmetic right
shift yields the sign fill (`0` or `-1`). RTMQ instructions masking the count to
five bits are target primitives, not source semantics. A negative count is
interpreted as an out-of-range unsigned count and produces the same saturated
result without a separate trap. Target lowering may emit one native shift when
range analysis proves the count is between 0 and 31.
_Avoid_: Modulo-32 shift
