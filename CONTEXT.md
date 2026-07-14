# CatSeq Sequencing

CatSeq models immutable, composable hardware timelines and compiles them into
board-specific instructions with exact timing and state continuity.

## Language

**Lane**:
The ordered, immutable sequence of operations for one hardware channel, together
with its total duration and boundary states. Its public operation sequence is a
tuple.
_Avoid_: Channel sequence, track

**OASM Call Plan**:
The epoch-segmented, board-grouped target calls produced after RTMQ linking and
consumed by the OASM assembler. Calls use offsets from either the initial origin
or a runtime Sync Phi release. It is the final Rust compiler artifact in CatSeq
0.3, not assembly text or an RTMQ binary.
_Avoid_: OASM assembly, RTMQ binary

**Runtime Slot**:
A stable symbolic identifier for one externally supplied scan input. Its value
is absent during source compilation and specialization and is supplied through
Runtime Bindings when the relative RTMQ program is linked.
_Avoid_: Scan symbol, compile-time parameter

**Scan Parameter**:
A Compile-known typed handle naming one Runtime Slot family. Indexing Scan
Bindings with it produces a Link value of the declared scalar type.
_Avoid_: Runtime Slot value, arbitrary mapping key

**Value Availability**:
The earliest context in which a typed value is concrete: Compile, Link, or
Device. Availability qualifies a base type rather than creating separate
runtime versions of every type.
_Avoid_: Compilation stage, Runtime type wrapper

**Type Signature**:
The stable base and nominal input, field, local, and result types inferred for a
definition SCC, independent of Value Availability and specialization values.
_Avoid_: Runtime-qualified type, Specialization Key

**Availability Transfer**:
The per-definition summary of how input Value Availability constrains or
determines expression and result availability across resolved calls.
_Avoid_: Type Signature, Dependency Role

**Compile Environment**:
The immutable source-external facts available while a sequence is analyzed and
specialized, such as hardware mappings, calibration snapshots, and registered
intrinsic signatures. Runtime scan values are not part of it.
_Avoid_: Python object graph, runtime globals

**Compile Request**:
The versioned one-shot binary input naming a Source Bundle, compile entry,
Compile Environment, Target Profile, optional Link Bindings, and incremental
cache. It contains no Python objects or syntax trees.
_Avoid_: Python compiler callback, daemon session request

**Target Profile**:
The versioned RTMQ ABI, board capabilities, clock definition, and Atomic Schema
target mappings against which a program is lowered.
_Avoid_: Hardware map, Compile Environment

**Relocatable Artifact**:
The target-specific Python-free RTMQ fragment DAG reusable across Link Bindings.
It has completed target lowering while retaining relative typed Link Values,
relocation metadata, and dependency indexes.
_Avoid_: OASM Call Plan, Morphism source object

**Canonical Program**:
The target-independent work product owning canonical Morphism and Value
Expression arenas, completed Morphism Effects, native schemas, and provenance.
_Avoid_: Relocatable RTMQ artifact, Source HIR

**Relative RTMQ Fragment**:
A target-lowered board/Epoch work unit whose event offsets and operands remain
relative Value Expressions until link. Fragments retain DAG composition and
Link Slot dependencies.
_Avoid_: Flat absolute event list, OASM Call Plan

**RTMQ Fragment Template**:
The target-specific per-definition fragment work product containing reusable
event ranges, duration, board membership, Link dependencies, and provenance.
Calls instantiate it without copying its events.
_Avoid_: Flattened board program, Morphism Template

**Source Bundle**:
The explicit set of project source roots and module identities available to the
binary compiler. It replaces Python's runtime import path and import hooks.
_Avoid_: PYTHONPATH, live module registry

**Source Module**:
A project Python module that the binary compiler may parse statically when a
reachable definition requires one of its exports.
_Avoid_: Imported PyModule, executed module

**Module Index**:
The declaration-only inventory of a parsed Source Module, containing imports,
signatures, decorators, and stable definition identities without semantically
analyzing every function body.
_Avoid_: Executed module namespace, whole-module Typed HIR

**Global Definition**:
A stable, lazily evaluated compile-visible module binding whose pure initializer
produces a native scalar, handle, record, Channel, or Compile Instance without
executing the Python module body.
_Avoid_: Python module global, eager module initializer

**Definition Key**:
The deterministic source identity of a definition, formed from its Source
Bundle, canonical module, qualified lexical name, and definition kind. A
compiler session interns it as a dense Definition ID.
_Avoid_: Source hash, specialization identity

**Definition Revision**:
An immutable semantic version of one Definition Key, with separate normalized
interface and implementation digests. Source edits create revisions without
changing the definition's logical identity.
_Avoid_: Definition ID, file modification time

**Specialization Key**:
The cache identity of one compiled Definition Revision under its compile-time
structural arguments, instance bindings, relevant environment facts, and
dependency revisions. Link-time Runtime Slot values are excluded.
_Avoid_: Definition Key, scan-point key

**Query DAG**:
The compiler-session graph of Dep Nodes and the exact ordered inputs or earlier
query results each query read. Rustc-style red-green fingerprint propagation
uses it to limit recomputation; it is not part of the compiled Morphism program.
_Avoid_: Morphism DAG, manual invalidation list

**Dep Node**:
One invocation of a compiler query, identified across sessions by its query kind
and a stable fingerprint of its key. Its result fingerprint and ordered
dependency edges support red-green validation without loading its cached value.
_Avoid_: Morphism node, session-local query index

**Stable Fingerprint**:
A 128-bit hash of a query key or semantic result after session-local identities
are mapped to stable forms. Key and result fingerprints are distinct and omit
source trivia, absolute spans, pointers, and arena indices.
_Avoid_: Object hash, raw source checksum

**Incremental Session**:
The immutable on-disk Query DAG, stable fingerprints, selected query results,
and compiled work products from one successful one-shot compiler invocation.
The next invocation reads it and atomically publishes its replacement.
_Avoid_: Compiler daemon, mutable global cache

**Work Product**:
A persistable native compilation result whose reuse justifies serialization,
such as an arena template or relative RTMQ artifact.
_Avoid_: Every query value, temporary compiler object

**Projection Query**:
A fine-grained query that exposes one stable definition or field from a larger
aggregate result, preventing unrelated aggregate changes from propagating to
its dependents.
_Avoid_: Whole-module consumer, copied result

**Query Provider**:
A deterministic compiler function whose only inputs are its key, declared input
Dep Nodes, and other query results. It returns value and diagnostics data and
has no externally observable side effects.
_Avoid_: Compiler callback with ambient I/O, Python hook

**Diagnostic Set**:
The stable Source-Anchor-based errors and warnings returned as query data and
aggregated for a compile entry. It can be cached without replaying output side
effects.
_Avoid_: Printed diagnostic, absolute-span log

**Source Anchor**:
A stable provenance identity formed from a Definition Key and owner-local source
node identity. The current source session resolves it to a concrete span.
_Avoid_: Persisted byte offset, Source HIR pointer

**Intrinsic Module**:
A compiler-registered module whose symbols, types, and lowering rules are
implemented natively rather than obtained by parsing or executing Python.
_Avoid_: Built-in Python module, runtime extension module

**Intrinsic Registry**:
The versioned native definitions exported by Intrinsic Modules: Atomic Schemas,
precompiled Morphism Templates, constants, scalar operations, and compiler
Special Forms.
_Avoid_: Imported Python library, arbitrary Rust callback table

**Atomic Schema**:
The declarative signature, parameter constraints, hardware effect, timing
contract, and target lowering identity for one primitive Atomic Operation.
_Avoid_: Python AtomicMorphism object, opaque code generator

**Compiler Special Form**:
One of the small closed set of intrinsic operations whose lowering changes
language structure, such as replacement, template binding, identity, or loop
formation.
_Avoid_: General intrinsic function, Python fallback

**Host Module**:
A module outside the restricted CatSeq language. Its import may remain
unloaded when it is unreachable from a compiled entry, but any reachable use
is a compile error.
_Avoid_: Unsupported Source Module, implicit Python fallback

**Typed Source HIR**:
Restricted-source HIR whose names resolve to stable definitions and whose
reachable expressions have CatSeq compiler types. It is the semantic boundary
between Python-shaped source and Morphism arena lowering.
_Avoid_: Annotated AST, runtime-typed HIR

**Source HIR Segment**:
The immutable flat node and edge ranges for one definition revision in the
compiler session's Source HIR store. Cross-definition references use stable
definition identities rather than node pointers.
_Avoid_: Recursive function tree, whole-module HIR

**Semantic Facts**:
The side tables keyed by Source HIR node identity that hold resolved names,
types, Value Availability, compile-time values, and other analysis results.
Together with a Source HIR Segment they form Typed Source HIR.
_Avoid_: Copied typed AST, mutable node annotations

**Abstract Evaluator**:
The Rust specializer that consumes Typed Source HIR and directly emits native
Value Expressions and Morphism nodes using a closed family of non-Python
values.
_Avoid_: Python interpreter, persistent normalized HIR

**Compile Reachability**:
Membership in the restricted CatSeq language, beginning at an explicit Compile
Entry and extending transitively through resolved calls, property reads, and
required constructors. It classifies definitions rather than whole Python
classes or modules.
_Avoid_: Compiled class, compiling every method

**Compile Instance**:
The immutable native projection of compile-reachable fields and stable identity
used when compiled definitions access an experiment, service, or module. It is
derived from source declarations and Compile Environment bindings,
independently of any live Python object or host lifecycle.
_Avoid_: Python object snapshot, imported singleton

**Native Handle**:
A Compile-known typed ID for a Board, nominal Channel, Compile Instance, Scan
Parameter, or another registered compiler entity. It is not a Python object or
first-class callable.
_Avoid_: Python reference, native record

**Native Record**:
A value of a registered fixed field schema used by Atomic Operations and
hardware configuration. It is flattened to typed payloads or relocations before
canonical Morphism publication.
_Avoid_: Python dataclass object, dynamic dictionary

**Compile Class Schema**:
The static native field, class-constant, method, and property model derived from
an explicit dataclass or registered dataclass-transform class family without
executing Python class construction.
_Avoid_: Python class object, metaclass result

**Host Object**:
The ordinary CPython instance used for setup, persistence, analysis, and device
lifecycle. Its existence and mutations do not provide values to the binary
compiler.
_Avoid_: Compile Instance, compiler object graph

**Contextual Aggregate**:
A Typed Source HIR value admitted only in a statically understood context, such
as channel bindings or a fixed Atomic Operation argument aggregate. It must be
eliminated during specialization or typed lowering and never becomes a
Morphism arena container node.
_Avoid_: Runtime container, arena list node

**Value Expression Arena**:
The native typed DAG of constants, Runtime Slots, Environment Slots, and
supported scalar operations referenced by Atomic Operation payloads and timing
expressions. It contains no Python AST or Source HIR nodes and is distinct from
the Morphism Arena that stores sequencing structure.
_Avoid_: Python expression arena, source payload store

**Runtime Bindings**:
The link-time mapping from Runtime Slots to the concrete values for one scan
point. Time-valued slots use integer Cycle Counts before RTMQ linking. Changing
Runtime Bindings does not change source specialization.
_Avoid_: Compile Environment, specialization parameters

**Environment Slot**:
A stable Value Expression input for a topology-independent scalar supplied by
the Compile Environment but deliberately left relocatable until RTMQ linking.
_Avoid_: Runtime Slot, structural specialization argument

**Link Bindings**:
The complete link-time values for Runtime Slots and Environment Slots. They are
consumed by Rust RTMQ linking before the OASM Call Plan is emitted.
_Avoid_: Compile Environment, Specialization Key

**Dependency Role**:
Whether a value use is Structural and must affect specialization, or
Relocatable and may remain a Link Value. It is independent of the value's
earliest Value Availability.
_Avoid_: Value Availability, base type

**Structural Dependency Summary**:
The exact structural arguments, instance and hardware bindings, environment
facts, and callee results that one definition specialization depends on.
_Avoid_: Whole Compile Environment hash, Query DAG

**Parallel Alignment**:
The Morphism algebra rule that every branch of a parallel composition ends at
one shared boundary. The result duration is the maximum branch duration, and
each shorter branch holds its final state until that boundary.
_Avoid_: Max-only parallelism, unaligned parallel branches

**Serial**:
An ordered Morphism composition whose adjacent boundaries independently use
automatic or strict state matching.
_Avoid_: Sequence node, chain node

**Parallel**:
A Morphism composition whose branches share their start and aligned end
boundaries and whose channel effects must be compatible.
_Avoid_: Concurrent list, max-duration group

**Loop Region**:
A Typed Source HIR sequencing loop with an induction variable, range,
loop-carried values, body, and yielded Morphism. It preserves source loop
semantics without copying the body into a Serial chain.
_Avoid_: Compile-time unrolling, Python iterator

**Loop**:
A canonical Morphism control node that repeats one body by a typed trip-count
Value Expression and retains the body's Morphism Effect for native target-loop
lowering.
_Avoid_: Repeated Serial children, opaque loop black box

**Morphism**:
A channel-bound sequencing state transformer. It may contain Link Values; its
incoming hardware state is supplied implicitly by Serial composition rather
than carried as a source-language value.
_Avoid_: Sequence object, Lane collection

**Morphism Template**:
A reusable Morphism definition with free channel slots. Its Python API spelling
is `MorphismDef`; binding its slots produces a Morphism template instance rather
than executing a Python generator. State remains an implicit Morphism effect.
_Avoid_: Python generator, deferred callable

**Morphism Effect**:
The symbolic state and timing transformation of a Morphism from its implicit
incoming State Environment to its outgoing State Environment.
_Avoid_: End-state dictionary, Lane summary

**State Environment**:
The compiler's channel-to-state relation at one Morphism boundary. It is
threaded through Serial composition and is not a source-language mapping value.
_Avoid_: StateMap, explicit start-state argument

**Phase Frame**:
The logical reference phase of one coherent drive group. A frame may govern
several physical channels with calibrated relative offsets; it is threaded
through Morphism Effects and is not a mutable tracker or a per-channel absolute
oscillator phase.
_Avoid_: Global phase, tracker field, channel absolute phase

**Phase Turn**:
The canonical Phase Frame unit in which `0.0` is zero phase and `1.0` is `2π`.
Finite frame values are normalized modulo one into `[0.0, 1.0)`.
_Avoid_: Radian phase, hardware phase word

**Phase Frame Definition**:
A Module's reusable declaration of one coherent drive group and its semantic
member roles, independent of a particular hardware deployment.
_Avoid_: Inferred channel pair, physical frame instance

**Phase Frame Binding**:
The Compile Environment association of a Phase Frame Definition's roles with
physical Channels and calibrated offsets for one module instance.
_Avoid_: Phase Frame Definition, method-body inference

**Channel Kind**:
A stable compiler identity for one hardware channel family, such as TTL, RWG,
or RSP. New hardware families may register new identities.
_Avoid_: Python channel class, board type

**State Type**:
A nominal hardware-state identity associated with one Channel Kind and used in
Morphism Effects and atomic transition rules. State Types are extensible
compiler definitions, not source values passed between services.
_Avoid_: Rust state enum, StateMap value

**Epoch**:
A time domain whose events use offsets from one shared origin. The initial
origin starts the first Epoch; a Sync Phi release starts a later Epoch.
_Avoid_: Global absolute timeline, phase

**Sync Phi**:
An executable cross-board rendezvous that merges runtime arrival timelines,
ends the current Epoch, and releases the next Epoch with one shared time origin.
It does not merge hardware states; every incoming path must first restore the
same externally visible state for each affected channel.
_Avoid_: Alpha Node, State Phi

**Atomic Operation**:
A sealed compiler-known operation that is either a hardware event or an opaque
region. Existing `AtomicMorphism`, `TimedRegion`, and `BlackBoxAtomicMorphism`
source values lower to this one Typed Source HIR family.
_Avoid_: Arbitrary atomic object, Python callable wrapper

**Timing Contract**:
The temporal guarantee of an opaque region. An Exact contract provides a
symbolic duration within the current Epoch; a Dynamic contract requires a Sync
Phi before static scheduling can resume.
_Avoid_: Cost estimate, timeout

**Cycle Count**:
The non-negative integer number of RTMQ clock cycles used as the canonical
representation of a Duration.
_Avoid_: Floating-point seconds, absolute timestamp

**Duration**:
A non-negative time interval whose concrete representation is a Cycle Count and
whose symbolic representation evaluates to a Cycle Count.
_Avoid_: Float, Timestamp

**Logical Timestamp**:
A time point identified by an Epoch and a non-negative cycle offset from that
Epoch's origin. Logical Timestamps from different Epochs are not directly
comparable or subtractable.
_Avoid_: Global cycle counter, Duration

**Cycle Quantization**:
An explicit conversion of a non-integral cycle quantity to a Cycle Count using
a declared floor, ceiling, or rounding policy. CatSeq performs no implicit Cycle
Quantization.
_Avoid_: Automatic rounding, floating-point truncation
