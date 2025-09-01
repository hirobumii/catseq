# Compiler Implementation Plan: Multi-Pass Pipelining Architecture

**Goal**: Refactor the compiler to a multi-pass architecture to support pipelined parameter loading and timing constraint checks for RWG operations.

**Core Concept**: We will separate the compilation into three distinct passes. This allows us to first understand the *cost* of operations, then check timing constraints, and finally generate the scheduled code.

**Core Data Structure**:
*   A new internal dataclass `LogicalEvent` will be created to represent each operation in the sequence. It will hold:
    *   `timestamp: int` (in cycles)
    *   `operation: AtomicMorphism`
    *   `cost_in_cycles: int` (calculated in Pass 1, for `LOAD` ops)

---

### **Pass 1: Cost Analysis**

**Goal**: Determine the execution time (cost) for every parameter-loading operation.

1.  **Flatten Sequence**: The compiler will first traverse the input `Morphism` and convert it into a flat, time-sorted list of `LogicalEvent`s.
2.  **Calculate Costs**: It will iterate through this list.
    *   For each event of type `RWG_LOAD_COEFFS`, it will generate the necessary `OASMCall`s for `rwg_load_waveform` in memory.
    *   It will then pass these calls to a new internal function, `estimate_oasm_cost()`.
    *   **Assumption**: This function will eventually analyze the assembly to get a precise cost. For the initial implementation, it will return a reasonable, hard-coded estimate.
    *   The calculated cost will be stored in the `cost_in_cycles` field of the `LogicalEvent`.

**Output of Pass 1**: A list of all logical events, with every `LOAD` event annotated with its execution cost.

---

### **Pass 2: Pipelining and Constraint Checking**

**Goal**: Verify that each waveform segment is long enough to load the parameters for the next segment.

1.  **Identify `Play -> Load` pairs**: The compiler will loop through the cost-annotated list of `LogicalEvent`s.
2.  When it encounters an `RWG_UPDATE_PARAMS` event (let's call it `Play_A`), it will look ahead in the list to find the *next* `RWG_LOAD_COEFFS` event for the same channel (let's call it `Load_B`).
3.  **Check Constraint**: It will then perform the critical check:
    ```python
    if Play_A.duration < Load_B.cost_in_cycles:
        raise CompilationError(f"Timing violation: Waveform segment at {Play_A.timestamp} is too short to load parameters for the next segment.")
    ```

**Output of Pass 2**: The same list of events, but now verified for timing feasibility. No `OASMCall`s are generated yet.

---

### **Pass 3: Code Generation and Scheduling**

**Goal**: Generate the final, correctly scheduled list of `OASMCall`s.

1.  **Process by Timestamp**: This pass will work similarly to the old compiler, processing events timestamp by timestamp.
2.  **Smart Scheduling**: The key difference is how it handles `LOAD` operations.
    *   When processing the events at `Timestamp_A` (which includes `Play_A`), the compiler already knows from Pass 2 that it needs to execute `Load_B` during this time.
    *   It will generate the `OASMCall`s for `Play_A` (i.e., the call to `rwg_play`).
    *   It will *also* generate the `OASMCall`s for `Load_B` (the calls to `rwg_load_waveform`).
    *   Crucially, the `wait` commands will be adjusted so that the `Load_B` commands are scheduled to execute *during* the `Play_A` duration. The `wait` before `Play_A` will be shortened, and new, smaller `wait`s will be interleaved with the `Load_B` commands.
3.  **Masking**: The logic for combining simultaneous triggers (`pud`, `iou`, `rf_switch`) into a single masked `OASMCall` will be performed in this final pass.
