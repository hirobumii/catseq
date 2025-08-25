# Cat-SEQ: A Categorical Framework for Hardware Sequence Control

Cat-SEQ is a Python framework for designing and executing precisely-timed hardware control sequences, primarily tailored for complex applications like quantum physics experiments. It provides a high-level, declarative API to describe the *what* of an experiment, rather than the imperative *how*.

## The Core Philosophy

The theoretical foundation of Cat-SEQ is **Category Theory**, specifically the structure of **Monoidal Categories**. This approach allows us to move away from traditional, imperative scripting ("set this voltage, wait, trigger that channel") towards a declarative, compositional model.

In this paradigm:
- An **Object** represents the complete state of the experimental system at a single moment.
- A **Morphism** represents a physical process that evolves the system from one state to another over a duration of time.

Complex experimental sequences are built by composing these morphisms together, creating a structure that is modular, reusable, and easier to verify.

## The RTMQ Hardware Ecosystem

Cat-SEQ is designed to be the high-level control interface for the **RTMQ (Real-Time Microsystem for Quantum physics)** hardware ecosystem. This ecosystem consists of:

- **RTMQ Core:** A 32-bit real-time processor with a custom instruction set architecture (ISA) optimized for deterministic, low-latency control.
- **RTLink Network:** A specialized, decentralized networking protocol that connects multiple RTMQ-based nodes, enabling distributed, synchronized control with nanosecond precision.
- **Modular Hardware:** A chassis-based system with a central **QCtrl Master** module for communication and clock distribution, and various functional modules like the **QCtrl RWG** (Real-time Waveform Generator).

Cat-SEQ abstracts away the immense complexity of programming this distributed real-time system, allowing researchers to focus on the physics of their experiment.

## Key Features of Cat-SEQ

- **Declarative & Composable API:** Build complex sequences by combining simpler ones.
  - `@` for serial composition (one process after another).
  - `|` for parallel composition (processes happening at the same time).
- **Automatic Synchronization:** The framework automatically handles timing and synchronization across different hardware channels, ensuring that parallel operations have equal duration by inserting waits where necessary.
- **Deferred Execution (`MorphismBuilder`):** Define reusable sequence "recipes" that are independent of specific hardware channels. These recipes are only instantiated into concrete, executable sequences at the last moment.
- **Context-Aware Composition:** The framework can automatically infer the required starting state of a sequence module from the ending state of the previous one, enhancing modularity and reusability.

## Conceptual Usage Example

Here is a conceptual example of how to build a simple sequence using Cat-SEQ's functional API:

```python
# Import the morphism "factories"
from catseq.morphisms import ttl
from catseq.morphisms.common import hold

# 1. Define reusable "recipes" for operations using MorphismBuilder
#    (No concrete hardware state is created yet)
pulse_def = ttl.pulse(duration=10e-6)
wait_def = hold(duration=5e-3)

# 2. Compose the recipes to define the abstract shape of a sequence
sequence_def = pulse_def @ wait_def @ pulse_def

# 3. At the very end, apply the abstract sequence to a specific hardware channel
#    This executes the builders and generates a concrete, timed LaneMorphism.
from catseq.protocols import Channel
from catseq.hardware.ttl import TTLDevice

ttl0 = Channel("TTL_0", TTLDevice)
my_sequence = sequence_def(ttl0)

# `my_sequence` can now be passed to a compiler to be translated
# into RTMQ instructions for the target hardware.
```

## Project Status

This project is currently a work in progress. The core framework for sequence definition and composition is well-developed, but key components like the **compiler** (which translates the abstract sequence into hardware-specific RTMQ instructions) are not yet implemented.

## Documentation

- **Framework Design:** For a deep dive into the design, architecture, and concepts of the Cat-SEQ framework itself, please see `catseq/DEVDOC.md`.
- **Hardware & Protocols:** For detailed specifications of the RTMQ ISA, RTLink protocol, and hardware modules, please refer to the documents in the `doc/` directory.
