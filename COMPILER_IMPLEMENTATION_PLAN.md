# Compiler Implementation Plan: Four-Pass Pipelining Architecture

**Goal**: Refactor the compiler to a four-pass architecture to cleanly separate translation, cost analysis, constraint checking, and final code generation. This ensures a robust, maintainable, and efficient compilation process.

**Core Concept**: The compilation process is a pipeline that progressively enriches a list of `LogicalEvent` objects. Each pass takes the list, adds or modifies information, and passes it to the next. This approach is summarized as:
1.  **Decomposition**: The high-level sequence is decomposed into a series of isolated nodes (`LogicalEvent`s).
2.  **Translation**: Each node's abstract intent is translated into concrete action commands (`OASMCall`s).
3.  **Costing**: The resource cost (execution time) of each node is calculated based on its translated commands.
4.  **Validation**: Constraints between nodes are verified using the calculated costs.
5.  **Integration**: Nodes are integrated into a final, complete sequence with timing control instructions (`wait` calls) inserted between them.

**Core Data Structure**:
*   The internal `LogicalEvent` dataclass is enriched to carry information through the pipeline:
    *   `timestamp_cycles: int` (from Pass 0)
    *   `operation: AtomicMorphism` (from Pass 0)
    *   `oasm_calls: List[OASMCall]` (populated in Pass 1)
    *   `cost_cycles: int` (populated in Pass 2)

---

### **Pass 0: Event Extraction**

**Goal**: Decompose the input `Morphism` into a flat list of time-sorted logical nodes.
*   **Input**: `Morphism` object.
*   **Process**: Traverses the `Morphism` and creates a `LogicalEvent` for each atomic operation.
*   **Output**: A `List[LogicalEvent]`, representing the "isolated nodes" of the sequence.

---

### **Pass 1: Translation (Logical to OASM)**

**Goal**: Translate the abstract intent of each logical event into a concrete list of OASM DSL calls.
*   **Input**: `List[LogicalEvent]` from Pass 0.
*   **Process**:
    1.  Iterate through each `LogicalEvent`.
    2.  Based on the event's `operation.operation_type`, find the corresponding OASM DSL function (e.g., `RWG_LOAD_COEFFS` might map to an OASM function like `set_params`).
    3.  Extract the necessary arguments from `event.operation.end_state`.
    4.  Generate a list of one or more `OASMCall` objects representing the complete operation.
    5.  Store this list in the `event.oasm_calls` field.
*   **Output**: The same `List[LogicalEvent]`, but now every event is enriched with its corresponding `oasm_calls`.

---

### **Pass 2: Cost Analysis**

**Goal**: Determine the precise execution time (cost) for operations that require it (e.g., `LOAD` operations for pipelining).
*   **Input**: Translated `List[LogicalEvent]` from Pass 1.
*   **Process**:
    1.  Iterate through each `LogicalEvent`.
    2.  If an event needs cost analysis (e.g., it's an `RWG_LOAD_COEFFS` operation):
        a. Take the `oasm_calls` list generated in the previous pass.
        b. Use a temporary `oasm.rtmq2.assembler` to convert these calls into RTMQ assembly instructions *once*.
        c. Analyze the generated assembly to calculate the total cycle cost.
    3.  Store the result in the `event.cost_cycles` field.
*   **Output**: The `List[LogicalEvent]`, now with `cost_cycles` annotated on relevant events.

---

### **Pass 3: Pipelining and Constraint Checking**

**Goal**: Verify that the sequence is physically possible, given the hardware's timing constraints.
*   **Input**: Cost-annotated `List[LogicalEvent]` from Pass 2.
*   **Process**: This pass performs the critical check for pipelining:
    ```python
    if Play_A.duration < Load_B.cost_cycles:
        raise CompilationError("Timing violation...")
    ```
*   **Output**: A validated `List[LogicalEvent]`.

---

### **Pass 4: Code Generation and Scheduling**

**Goal**: Assemble the final, correctly scheduled list of `OASMCall`s, including all timing delays.
*   **Input**: Validated `List[LogicalEvent]` from Pass 3.
*   **Process**: This pass is now greatly simplified:
    1.  Iterate through the time-sorted events.
    2.  Calculate the required delay (`wait`) since the last event.
    3.  Append the `wait` call to the final output list.
    4.  Append the **pre-translated `oasm_calls`** from the current event directly to the output list.
*   **Output**: The final, flat `List[OASMCall]` ready for execution.