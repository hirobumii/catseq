# Cat-SEQ Framework Architecture

*This document describes the ideal architecture of the `catseq` framework and how it should be used in a concrete experiment. This is based on the design intent as of 2025-08-25.*

The system is divided into two primary components: the **Framework Library** (`catseq`) and the **Experiment Application** (a separate, user-created folder).

---

## Part 1: The `catseq` Framework Library

The `catseq` package is a self-contained, hardware-agnostic library for building categorical sequences. It provides the core engine and a "standard library" of generic components.

### Layer 0: Core Protocols (`catseq/protocols.py`)
*   **Purpose**: Defines the abstract "language" of the entire system.
*   **Key Components**: `State`, `Channel`, `HardwareInterface`, etc.
*   **Dependency Rule**: Has no dependencies on other modules within `catseq`.

### Layer 1: Algebraic Engine (`catseq/model.py`, `catseq/builder.py`)
*   **Purpose**: Implements the core logic for composing (`@`, `|`) and building morphisms.
*   **Key Components**: `LaneMorphism`, `MorphismBuilder`.
*   **Dependency Rule**: Depends only on Layer 0.

### Layer 2: Standard Hardware Vocabulary (`catseq/hardware/`, `catseq/states/`)
*   **Purpose**: Provides a "batteries-included" set of generic, reusable **definitions** for common hardware types.
*   **Key Components**: The `TTLDevice` and `RWGDevice` *classes*, and the `TTLState`, `RWGActive` *state definitions*.
*   **Dependency Rule**: Depends only on Layer 0.

### Layer 3: Standard Morphism API (`catseq/morphisms/`)
*   **Purpose**: Provides convenient factory functions for the standard hardware types.
*   **Key Components**: `ttl.pulse`, `rwg.linear_ramp`.
*   **Dependency Rule**: Depends on all lower-level framework layers.

---

## Part 2: The Experiment Application

This is a separate folder, created by the user, that sits alongside the `catseq` library folder. It uses `catseq` as an imported library.

### `my_experiment/` (Example)

*   **Purpose**: To define a specific machine's physical layout and to build and run experimental sequences.
*   **Responsibilities**:
    *   **Channel Instantiation**: This is the primary role. Scripts in this folder will import classes from `catseq.hardware` and create concrete channel **instances**.
      ```python
      # In my_experiment/my_machine_setup.py
      from catseq.hardware.ttl import TTLDevice
      from catseq.protocols import Channel

      # Defines the specific channels for this experiment
      TTL_0 = Channel("TTL_0", TTLDevice)
      PUMP_LASER_TTL = Channel("PUMP_AOM", TTLDevice)
      ```
    *   **Sequence Composition**: Scripts will import morphism factories from `catseq.morphisms` and use the instantiated channels to build the final experimental sequence.
    *   **Execution**: This layer is responsible for taking the final `LaneMorphism` object and passing it to a compiler or hardware driver.
