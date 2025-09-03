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
*   **Process**: This pass performs critical hardware constraint validation:
    ```python
    if Play_A.duration < Load_B.cost_cycles:
        raise CompilationError("Timing violation...")
    ```
    
#### **Hardware Constraints for RWG Operations**

**SBG Resource Constraints**:
- Each board has shared SBG (Signal Block Generator) resources
- Multiple channels on the same board cannot use the same SBG ID simultaneously
- Compiler must detect and report SBG resource conflicts at compile time

**LOAD Operation Constraints**:
- Same board: Multiple `RWG_LOAD_WAVEFORM` calls must execute **strictly serially**
- Each `RWG_LOAD_WAVEFORM` takes exactly 14 cycles
- Total cost for N loads = `14 × N` cycles (cumulative, not parallel)

**LOAD-PLAY Timing Constraints**:
- **Same Channel (Strict)**: 
  ```
  LOAD operations must complete ENTIRELY before PLAY starts
  If LOAD requires 1400 cycles but only 1200 cycles available → Compilation Error
  ```
- **Different Channels (Flexible)**:
  ```
  Channel 0 PLAY can run in parallel with Channel 1 LOAD operations
  No timing conflicts between cross-channel LOAD-PLAY operations
  ```

**Cross-Channel Pipelining Optimization**:
- Channel 1's LOAD can be scheduled during Channel 0's PLAY period
- Enables efficient utilization: `PLAY0 || LOAD1` → `PLAY1`
- Scheduler should minimize parameter pre-load time while meeting deadlines

*   **Output**: A validated `List[LogicalEvent]`.

---

### **Pass 4: Code Generation and Scheduling**

**Goal**: Assemble the final, correctly scheduled list of `OASMCall`s with intelligent pipelining optimization.
*   **Input**: Validated `List[LogicalEvent]` from Pass 3.
*   **Process**: Enhanced scheduling with cross-channel pipelining:
    
#### **Intelligent Pipelining Scheduler**:

1. **Pipeline Pair Identification**:
   
   **What is a Pipeline Pair?**
   A pipeline pair consists of a `LOAD` operation and its corresponding `PLAY` operation that form a logical sequence:
   ```python
   # Example: set_state() generates a LOAD → PLAY pair
   set_state([target]) → rwg_load_coeffs() >> rwg_update_params()
                        ↑ LOAD event      ↑ PLAY event  
                        └─── Pipeline Pair ────┘
   ```
   
   **Pair Identification Logic**:
   ```python
   # Find LOAD → PLAY operation sequences for pipelining optimization
   for load_event in load_events:
       # A LOAD pairs with the next UPDATE_PARAMS on the same channel
       corresponding_play = find_next_same_channel_play(load_event)
       if corresponding_play:
           pipeline_pairs.append((load_event, corresponding_play))
   
   def find_next_same_channel_play(load_event):
       """Find the first UPDATE_PARAMS event on the same channel after the LOAD"""
       load_channel = load_event.operation.channel
       load_time = load_event.timestamp_cycles
       
       for event in events_after(load_time):
           if (event.operation.channel == load_channel and 
               event.operation.operation_type == OperationType.RWG_UPDATE_PARAMS):
               return event
       return None
   ```
   
   **Why Pairs Matter**: 
   - The LOAD operation configures parameters that the PLAY operation will use
   - The PLAY operation cannot start until its corresponding LOAD is complete
   - Cross-channel optimization: LOAD₁ can execute during PLAY₀ if they're from different pairs

2. **Cross-Channel Schedule Optimization**:
   ```python
   # Example: Channel 1 LOAD during Channel 0 PLAY
   # Original: WAIT(10μs) → LOAD1(1400c) → PLAY1
   # Optimized: LOAD1(1400c) → WAIT(8.4μs) → PLAY1 (starts during PLAY0)
   
   for load_event, play_event in pipeline_pairs:
       # Calculate optimal LOAD start time
       play_deadline = play_event.timestamp_cycles  
       load_duration = load_event.cost_cycles
       optimal_load_start = max(0, play_deadline - load_duration)
       
       # Ensure no conflicts with serial LOAD constraints
       schedule_load_event(load_event, optimal_load_start)
   ```

3. **Final Assembly**:
   - Sort all events (including rescheduled LOADs) by new timestamps
   - Insert appropriate `WAIT_US` calls between operations  
   - Generate final `List[OASMCall]` sequence

#### **Optimization Benefits**:
- **Reduced Latency**: LOAD operations execute during other channels' PLAY periods
- **Hardware Utilization**: Maximizes parallel use of LOAD and PLAY resources
- **Deterministic Timing**: Maintains user-specified PLAY start times

#### **Scheduling Example**:

**User Intent**:
```python
# Two channels with offset timing
ch0_sequence = identity(10e-6) >> set_state([target0])  # PLAY at t=10μs  
ch1_sequence = identity(15e-6) >> set_state([target1])  # PLAY at t=15μs (100 params = 1400c)
parallel = ch0_sequence | ch1_sequence
```

**Generated Pipeline Pairs**:
```python
# After Pass 0 (Event Extraction):
Pair 0: (LOAD0@t=10μs, PLAY0@t=10μs)   # Channel 0 pair
Pair 1: (LOAD1@t=15μs, PLAY1@t=15μs)   # Channel 1 pair (1400c LOAD cost)
```

**Naive Scheduling** (without cross-pair optimization):
```
t=0:     WAIT(10μs)
t=10μs:  LOAD0(14c) → PLAY0     # Pair 0 executes
t=10μs:  WAIT(5μs)              # Wait for Pair 1 deadline  
t=15μs:  LOAD1(1400c) → PLAY1   # Pair 1 executes
Problem: LOAD1 extends until t=20.6μs, delaying PLAY1!
```

**Optimized Cross-Pair Pipelining Schedule**:
```
t=0:     WAIT(9.4μs)           # Calculated: t=15μs - 1400c = t=9.4μs
t=9.4μs: LOAD1(1400c) begins   # Start Pair 1 LOAD early
t=10μs:  LOAD0(14c) → PLAY0    # Pair 0 executes (LOAD1 still running)
                               # Key: LOAD1 ∥ PLAY0 (different pairs!)
t=14.96μs: LOAD1 completes     # Pair 1 LOAD finishes
t=15μs:  PLAY1 starts on time  # Pair 1 PLAY executes
```

**Key Insights**:
1. **Pair Dependency**: PLAY1 depends only on LOAD1 completion, not LOAD0 or PLAY0
2. **Cross-Pair Parallelism**: LOAD1 can run during PLAY0 because they belong to different pipeline pairs
3. **Schedule Optimization**: Reschedule LOAD1 to start at `t_PLAY1 - cost_LOAD1` for optimal timing

*   **Output**: The final, optimally scheduled `List[OASMCall]` ready for execution.