# CatSeq Sequencing

CatSeq models immutable, composable hardware timelines and compiles them into
board-specific instructions with exact timing and state continuity.

## Language

**BaseExp**:
The lifecycle owner for one complete experiment execution, from setup through
scan traversal to finalization. It owns orchestration, not platform-specific
resource construction. Its public home is `catseq.experiment`, and CatSeq does
not split it into a separate Experiment Run object. It is imported from
`catseq.experiment.base_exp`; the namespace does not bulk re-export all
experiment types. Its orchestration is host Python; only `build_sequence` is
compiled separately for each attempted scan point.
_Avoid_: ExperimentRun, compile-and-run wrapper

**Experiment Control**:
The generic host-side lifecycle, scan traversal, device/result coordination,
analysis, panel publication, and H5 persistence exposed through focused public
modules under `catseq.experiment`. Target discovery, runtime
construction, hardware locks, and transport-specific publishers belong to
downstream adapters.
_Avoid_: rb1system.abstract, platform runtime factory

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

**Compiled Sequence**:
The immutable public result of compiling and linking one sequence entry. It
contains the OASM Call Plan, logical timing, and diagnostics, but no OASM
assembler context or physical execution state.
_Avoid_: seq, OASM assembler, live Python Morphism

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
intrinsic signatures. It is shared by compilations for one sequencing system;
Runtime scan values and physical execution settings are not part of it.
_Avoid_: Python object graph, runtime globals

**Entry Arguments**:
The explicitly supplied scalar arguments of the root sequence method. They are
Compile-known specialization inputs, may select structural control flow, and
are transported separately from Link-time Runtime Bindings. An omitted argument
uses its source default; explicit `None` is retained for an Optional parameter.
_Avoid_: Runtime Bindings, Runtime Slot values

**Compile Request**:
The versioned one-shot binary input naming a Source Bundle, compile entry,
Compile Environment, Entry Arguments, Target Profile, optional Link Bindings,
and incremental cache. It contains no Python objects or syntax trees.
_Avoid_: Python compiler callback, daemon session request

**Target Profile**:
The versioned RTMQ ABI, board capabilities, clock definition, and Atomic Schema
target mappings against which a program is lowered.
_Avoid_: Hardware map, Compile Environment

**Ethernet Runtime**:
The execution environment that dispatches assembled board programs to one
physical chassis through the RTLink Ethernet protocol. Platform-specific raw
socket or capture-driver mechanisms are not part of its public identity.
_Avoid_: Raw Ethernet Runtime, OASM eth_intf

**Relocatable Artifact**:
The target-specific Python-free RTMQ fragment DAG reusable across Link Bindings.
It has completed target lowering while retaining relative typed Link Values,
relocation metadata, and dependency indexes.
_Avoid_: OASM Call Plan, Morphism source object

**Canonical Program**:
The target-independent work product owning canonical Morphism and Value
Expression arenas, completed Morphism Effects, native schemas, and provenance.
_Avoid_: Relocatable RTMQ artifact, Source HIR

**Target-Resolved Native Arenas**:
The Python-free Morphism and Value Expression arena projection emitted by
`catseqc emit-arena` after SI units have been converted with one Target
Profile's clock. It is an intermediate compiler diagnostic, not the
target-independent Canonical Program.
_Avoid_: Canonical Program, OASM Call Plan

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
The versioned native definitions exported by Intrinsic Modules: Channel Kind
definitions and Boundary Schemas, Atomic Schemas, precompiled Morphism
Definitions, constants, scalar operations, and compiler Special Forms.
_Avoid_: Imported Python library, arbitrary Rust callback table

**Atomic Schema**:
The versioned declaration of the signature, parameter constraints, complete
input and output patterns and Boundary Binders over one Channel Kind's Boundary
Schema, timing contract, and target lowering identity for one primitive Atomic
Operation. It may contain a finite set of input-disjoint Boundary Transition
Clauses.
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
point. Time-valued slots use integer Cycle Deltas before RTMQ linking. Changing
Runtime Bindings does not change source specialization.
_Avoid_: Compile Environment, specialization parameters

**Environment Slot**:
A stable Value Expression input for a topology-independent scalar supplied by
the Compile Environment but deliberately left relocatable until RTMQ linking.
Its key is `<module>.<entry-class-or-singleton>.<field>`, so two Compile
Instances of the same class cannot alias one another's binding.
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
The sole ordered Morphism composition, spelled `>>`, that instantiates successor
Boundary Binders and then completely matches adjacent Boundary records.
_Avoid_: `@`, Auto Serial, Strict Serial, Sequence node, chain node

**Parallel**:
A Morphism composition whose branches share their start and aligned end
boundaries and whose Resource Supports must be pairwise disjoint.
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
A sequencing value indexed by a finite Resource Context and a typed Boundary
Contract. Resource Slot Binding substitutes logical resources without changing
the Morphism sort; the value may contain Link Values.
_Avoid_: Morphism Template, Morphism Family, Sequence object, Lane collection

**Morphism Definition**:
A restricted source declaration whose application produces a Morphism, possibly
with free Resource Slots. It is a declaration, not a second Morphism value
type; the current `MorphismDef` and `MorphismTemplate` spellings are legacy API
names rather than domain types.
_Avoid_: Morphism Template, Morphism Family, Python generator, deferred callable

**Resource Context**:
The finite typed set of formal Resource Slots referenced by a Morphism. A
Morphism is resource-closed when this context is empty.
_Avoid_: State Environment, runtime environment, physical hardware map

**Resource Slot Binding**:
The substitution of each formal Resource Slot in a Morphism with one compatible
logical Channel or resource identity. It preserves the Morphism sort and is
distinct from target lowering's logical-to-physical resource mapping.
_Avoid_: Morphism instantiation type, State transition, physical Board binding

**Boundary Contract**:
The complete typed entry and exit records for every Resource Slot a Morphism
uses. Each record contains only compiler-relevant facts, may reference immutable
Value Expressions, and explicitly carries through facts that remain unchanged.
_Avoid_: State Environment, whole-machine snapshot, hidden backend state

**Boundary Schema**:
The canonical versioned type of a Channel Kind's complete compiler-relevant
boundary record. Every Atomic Schema for that Channel Kind uses this shared
type for its input and output patterns.
_Avoid_: Atomic-specific record, target-backend state enum, physical state model

**Boundary Binder**:
A schema-internal symbolic name bound to a field of an Atomic Operation's input
Boundary Schema pattern so its output record or Value Expressions can reference
the predecessor-provided value.
_Avoid_: Source variable, Device Value, runtime parameter, backend state lookup

**Boundary Transition Clause**:
One complete input-pattern and output-record rule for a legal case of an Atomic
Operation. An Atomic Schema's clauses have disjoint input patterns and are
the cases of one deterministic, piecewise partial Boundary Transformer. A
context-open Morphism preserves that transformer, and Serial composes it with
adjacent transformers. This is static Morphism semantics, not runtime Control.
_Avoid_: Hardware branch, ordered fallback, partial boundary record

**Boundary Transformer**:
The deterministic partial function from complete input Boundary records to
complete output Boundary records and value derivations denoted by a Morphism.
Mutually exclusive Boundary Transition Clauses define its pieces; it is a
semantic contract, not a runtime node or a set of competing choices.
_Avoid_: Candidate clause set, Control Choice, backend state transition

**Context-open Morphism**:
A Morphism with at least one mandatory Boundary Contract requirement not yet
connected to an explicit predecessor provision inside the composed expression.
_Avoid_: OpenMorphism type, resource-open Morphism, invalid Morphism

**Context-closed Morphism**:
A Morphism whose mandatory Boundary Contract requirements are all connected to
explicit predecessor provisions inside the composed expression, leaving an
empty external `Requires` set.
_Avoid_: Resource-closed Morphism, fully lowered program, state-complete Morphism

**Selected Compile Entry**:
The reusable Kernel Function chosen as the standalone root of one compilation.
Its resulting Morphism must be both resource-closed and context-closed before
target lowering. Reusable definitions and Kernel Functions that are only called
as helpers may remain context-open; their requirements propagate to their
caller. The Compile Environment does not satisfy mutable Boundary requirements.
_Avoid_: Ambient root state, session-provided Boundary record, every Kernel
Function must be closed

**Morphism Effect**:
The explicit temporal, resource, value, protocol, and Boundary Contract summary
derived from a Morphism. It is not an ambient hardware-state transformation.
_Avoid_: End-state dictionary, State Environment, Lane summary

**State Refinement**:
Optional hardware knowledge that can enrich analysis or diagnostics but cannot
change Morphism legality, emitted payloads, timing, resources, values, or
mandatory failure behavior.
_Avoid_: Boundary Contract, required protocol fact, lowering input

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
or RSP, together with its canonical Boundary Schema. New hardware families may
register new identities.
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

**Opaque Region**:
An exact-duration Morphism produced by `catseq.oasm.black_box`, carrying one
stable host-callback identity per participating board and no channel-state
contract. It exclusively occupies each participating board over `[start, end)`,
so any intersecting ordinary same-board Morphism is invalid, including one that
begins earlier and spans the region. The end boundary may be the start of the
next Morphism. The native arena and OASM Call Plan contain no Python callable;
the host assembly adapter resolves the identity from the `CompiledSequence`
registry. Raw OASM state correctness is the user's responsibility.
_Avoid_: Downstream Atomic Schema shim, serialized Python closure

**Timing Contract**:
The temporal guarantee of an opaque region. An Exact contract provides a
symbolic duration within the current Epoch; a Dynamic contract requires a Sync
Phi before static scheduling can resume.
_Avoid_: Cost estimate, timeout

**Cycle Count**:
The non-negative integer number of RTMQ clock cycles used for an encoded
hardware interval or Logical Timestamp offset.
_Avoid_: Floating-point seconds, signed time displacement, absolute timestamp

**Cycle Delta**:
A signed integer number of RTMQ clock cycles used as the canonical
representation of a Duration.
_Avoid_: Cycle Count, absolute timestamp

**Duration**:
A signed logical time displacement whose concrete representation is a Cycle
Delta. A negative Duration moves the Logical Timestamp backward within its
Epoch; it is not a negative hardware wait.
_Avoid_: Float, Timestamp, Cycle Count

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
