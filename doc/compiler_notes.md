# Compiler Implementation Notes

This document provides an overview of the CatSeq compiler's architecture and current status, intended for developers continuing its implementation.

## 1. Multi-Pass Architecture

The compiler is designed with a multi-pass architecture to handle complex scheduling and optimization, particularly for pipelined hardware operations. The main entry point is `compile_to_oasm_calls()`.

### Pass 0: Event Extraction (`_pass0_extract_events`)
*   **Purpose**: Flattens the input `Morphism` into a time-sorted list of `LogicalEvent` objects, grouped by board.
*   **Status**: Implemented and stable. Extracts all `AtomicMorphism`s from the `Morphism`'s lanes and converts them into `LogicalEvent`s with their logical timestamps.

### Pass 1: Cost Analysis (`_pass1_analyze_costs`)
*   **Purpose**: Annotates `LogicalEvent`s with their estimated execution cost in hardware clock cycles.
*   **Status**: Implemented with a **placeholder cost model**. Currently, it only calculates costs for `RWG_LOAD_COEFFS` operations (e.g., `num_params * 20` cycles).
*   **Future Work**: The `estimate_oasm_cost()` function (or similar logic within this pass) needs to be implemented to accurately determine the cycle cost by analyzing the generated OASM assembly for specific operations.

### Pass 2: Pipelining and Constraint Checking (`_pass2_check_constraints`)
*   **Purpose**: Verifies timing constraints, especially for pipelined operations (e.g., ensuring a `Play` segment is long enough to load parameters for the next segment).
*   **Status**: Implemented for basic `RWG_UPDATE_PARAMS` -> `RWG_LOAD_COEFFS` pipelining. It raises a `ValueError` if a timing violation is detected.
*   **Future Work**: Extend to cover more complex pipelining scenarios or other hardware-specific timing constraints.

### Pass 3: Code Generation and Scheduling (`_pass3_generate_oasm_calls`)
*   **Purpose**: Generates the final, scheduled list of `OASMCall`s, performing the actual pipelining of instructions.
*   **Status**: Implemented with **basic pipelining logic** for `RWG_LOAD_COEFFS` operations. It adjusts `WAIT_US` calls to absorb the cost of pipelined loads.
*   **Key Logic**: It maintains a `pipelined_load_cost` variable to adjust subsequent `WAIT_US` calls. When an `RWG_UPDATE_PARAMS` (Play) operation occurs, it looks ahead to find the next `RWG_LOAD_COEFFS` (Load) operation for the same channel and generates its `rwg_load_waveform` calls immediately after the `rwg_play` call.
*   **Future Work**: 
    *   **Full RWG Support**: Currently, only `RWG_INIT`, `RWG_LOAD_COEFFS`, `RWG_RF_SWITCH`, and `RWG_UPDATE_PARAMS` are handled. Other RWG operations (if any) need to be added.
    *   **Generalization**: The pipelining logic is currently specific to `RWG_LOAD_COEFFS` and `RWG_UPDATE_PARAMS`. Consider generalizing this for other types of pipelined operations.
    *   **Optimization**: Further optimize instruction scheduling for tighter packing or specific hardware features.

## 2. Atomic DSL Functions

The compiler generates calls to a set of atomic DSL functions defined in `compilation/functions.py`. These are placeholders that need their actual OASM assembly generation logic implemented.

**Current RWG-related DSL functions:**
*   `rwg_initialize_port(rf_port: int, carrier_mhz: float)`
*   `rwg_rf_switch(rf_mask: int, on: bool)`
*   `rwg_load_waveform(params: WaveformParams)`
*   `rwg_play(duration_us: float, pud_mask: int, iou_mask: int)`

## 3. Testing

*   Unit tests for each pass (e.g., `test_compiler_rwg.py`) verify the individual pass's logic.
*   Integration tests (`test_catseq_to_rtmq_pipeline.py`) verify the end-to-end compilation for TTL operations.
*   **Crucial**: New tests are needed to thoroughly verify the pipelining logic, especially the exact sequence and arguments of generated `OASMCall`s for complex RWG sequences.
