# CatSeq: Mathematical Foundations & Formal Specification

## 1. Category Definition

We define **CatSeq** as a **Strict Symmetric Monoidal Category** , where:

* **Objects ()**: Finite sets of physical hardware channels (e.g., , ).
* **Morphisms ()**: A morphism  represents a time-bounded control sequence acting on the set of channels , transforming them into .
* In the simplified topological view, . Thus, a morphism is an endomorphism over a set of resources.
* Every morphism  possesses a scalar property .



## 2. Compositional Laws (The Box Model)

CatSeq enforces a **Rectangular Box Model**, meaning every morphism acts as a rigid, time-bounded block.

### 2.1 Sequential Composition (`@`)

Corresponds to the `catseq.compos` operation.
Let  and  be morphisms. The composition  (denoted ) is defined if and only if their channel resources align.

* **Topological Constraint:**  (Strict) or valid under the *Union-Padding Principle* (see Section 4).
* **Temporal Property:**


* **Associativity:** .

### 2.2 Parallel Composition (`|`)

Corresponds to the `catseq.tensor` operation.
Let  and  be morphisms. The tensor product  (denoted ) is defined if and only if their resources are disjoint.

* **Topological Constraint:** .
* **Temporal Property (Synchronization Barrier):**


* **Rectangularity:** The resulting morphism  acts as a synchronized block. If , the shorter branch is implicitly padded with Identity.

---

## 3. The Synchronization Law (Modified Interchange)

In standard Category Theory, the interchange law states .
In **CatSeq**, due to physical duration constraints, this law is modified to explicitly account for temporal padding.

**Theorem:**
Given sequential blocks of parallel operations:


If , let .
If , let .

The effective execution sequence is:

Where  is an Identity morphism (Wait/No-op) of duration . This law guarantees that synchronization barriers established by `|` are respected by `@`.

---

## 4. The Union-Padding Principle

To improve expressiveness, CatSeq relaxes the strict channel equality requirement for Sequential Composition via the **Union-Padding Principle**.

Given  acting on channel set  and  acting on , the composition  is valid over the union set .

**Formal Transformation:**
The compiler automatically lifts  and  to  by tensoring with Identity morphisms for missing channels:

This ensures that a channel referenced in  but not in  waits idly during the execution of .

---

## 5. Closure and The `execute` Boundary

CatSeq distinguishes between **Open Fragments** (Library Code) and **Closed Executables** (Runtime Code). This distinction is enforced at the interface with the higher-level `program` dialect.

### 5.1 Open Morphisms (Fragments)

Any morphism constructed via `@` or `|` within CatSeq is considered **Open**.

* **State:** May start or end in any physical state (e.g., RF On, Voltage High).
* **Validation:** Only topological checks (resource conflicts) are performed.

### 5.2 The `execute` Operator

The operation `program.execute(m)` acts as a functor mapping a CatSeq morphism  into the Control Flow Graph (CFG) of the program.

**Validity Condition:**
A morphism  is valid for `program.execute` if and only if it is **Closed** with respect to the Program's resource lifecycle.

Let  be the hardware state before `execute(m)` and  be the state after.


For a sequence to be chemically/physically valid in a loop (Monad), the net transformation of resources must often be Identity (or explicitly managed via Active Reset).

**Deferred Verification:**
While CatSeq ensures internal topological consistency, the `execute` boundary triggers the **Semantic Verification Pass**:

1. **Initialization:** Does the channel path start with a defined state (via `Acquire` or inherited context)?
2. **Finalization:** Are resources released or in a safe state (via `Release` or context)?
3. **Leakage:** Are there unclosed side-effects (e.g., RF left ON) crossing the `execute` boundary?