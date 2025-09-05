# Refactored Compiler Architecture Plan

The compilation process will be restructured into a more logical flow of five passes. The key idea is to separate initial translation, timing optimization (scheduling), and final code generation into distinct, ordered phases.

## Pass 1: Event Extraction & Translation
*   **Name:** `_pass1_extract_and_translate_events`
*   **Responsibilities:**
    1.  **Flatten Morphism:** Decompose the input `Morphism` into a time-sorted list of `LogicalEvent`s per board.
    2.  **Initial Translation:** Translate each `LogicalEvent`'s intent into one or more `OASMCall` objects.
        *   `SYNC_SLAVE` is translated to `wait_master` (with merging logic).
        *   `SYNC_MASTER` is translated to `trig_slave`, but with a `WAIT_TIME_PLACEHOLDER` for the wait time.
*   **Output:** A dictionary of `LogicalEvent` lists, where each event has been populated with its corresponding (but not yet scheduled) `OASMCall`s.

## Pass 2: Cost & Epoch Analysis
*   **Name:** `_pass2_analyze_costs_and_epochs`
*   **Responsibilities:**
    1.  **Cost Analysis:** Analyze the cycle cost of each `OASMCall` list for each event and populate `event.cost_cycles`.
    2.  **Epoch Detection:** Scan the events to identify `global_sync` points and assign an `epoch` number to each `LogicalEvent`.
*   **Output:** The `LogicalEvent`s are now enriched with both `cost_cycles` and `epoch` information.

## Pass 3: Scheduling & Pipelining Optimization
*   **Name:** `_pass3_schedule_and_optimize`
*   **Responsibilities:**
    1.  **Identify Pipeline Pairs:** Find all potential `LOAD` -> `PLAY` pairs, allowing for cross-epoch pairing.
    2.  **Calculate Optimal Schedule:** Run the scheduling algorithm to move `LOAD` operations to their optimal, earlier timestamps, potentially across epoch boundaries.
*   **Output:** A list of `LogicalEvent`s with their `timestamp_cycles` updated to reflect the new, optimized schedule.

## Pass 4: Constraint Validation
*   **Name:** `_pass4_validate_constraints`
*   **Responsibilities:** Run checks on the final, scheduled timestamps.
    1.  Check for fundamental logical errors like negative wait times.
    2.  Verify that intra-epoch pipelining is valid (`duration(PLAY_A)` >= `cost(LOAD_B)`).
    3.  Verify `RWG_INIT` only occurs in `epoch 0`.
*   **Output:** Raises a `ValueError` if an unrecoverable scheduling conflict is found.

## Pass 5: Final Code Generation & Sync Time Calculation
*   **Name:** `_pass5_generate_final_calls`
*   **Responsibilities:**
    1.  **Calculate True Master Wait Time:** Find the maximum end time of all operations in `epoch=0` (including any `LOAD`s pulled in from `epoch=1`). This value (plus a safety margin) is the definitive `master_wait_time`.
    2.  **Backfill Placeholder:** Find the `trig_slave` call and replace the `WAIT_TIME_PLACEHOLDER` with the true wait time.
    3.  **Generate Final Call List:** Iterate through the final, sorted `LogicalEvent`s and generate the definitive list of `OASMCall`s for each board, inserting the necessary `wait_us` calls.
*   **Output:** The final `Dict[OASMAddress, List[OASMCall]]` ready for execution.