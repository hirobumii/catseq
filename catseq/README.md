# CatSeq: A Categorical Sequencer for RTMQ

## About

`catseq` is a powerful Python library for designing and compiling complex pulse sequences for quantum control hardware, specifically systems using the **RTMQ (Real-Time Microsystem for Quantum physics)** framework.

It provides a high-level, expressive framework for building intricate, time-sensitive, and synchronized hardware instructions from simple, reusable blocks. The core philosophy is based on **category theory**, allowing developers to compose complex sequences from simpler ones using intuitive operators.

This tool is designed for physicists and engineers working on quantum computing experiments who require precise, multi-channel, and synchronized control over their hardware.

## Installation

`catseq` is designed as an extension to the `oasm.dev` package. Installation is handled via `pip`:

```bash
pip install .
```

When you install `catseq`, a post-installation script automatically runs to copy the necessary extension files into your `oasm.dev` installation. This seamlessly integrates `catseq`'s capabilities into your existing OASM environment.

## Core Concepts

`catseq` is built on a few core concepts derived from category theory.

### Morphism

The central abstraction in `catseq` is the **`Morphism`**. A `Morphism` represents a sequence of hardware operations. It can contain operations for one or more hardware channels.

### Lane

A **`Lane`** represents the timeline of operations for a single hardware channel. A `Morphism` is composed of one or more `Lanes`.

### Composition

`catseq` provides three binary operators for composing `Morphism`s:

*   **`@` (Strict Sequential Composition):** This operator chains two `Morphism`s together sequentially. It enforces a strict contract, requiring the end state of every channel in the first `Morphism` to exactly match the start state of the corresponding channel in the second.
*   **`>>` (Inferred Sequential Composition):** This is a more lenient sequential composition operator. It also chains `Morphism`s together, but it automatically infers the necessary start states for the second `Morphism` based on the end states of the first. This is useful for more flexible composition.
*   **`|` (Parallel Composition):** This operator combines two `Morphism`s to run in parallel. The two `Morphism`s must operate on different channels. `catseq` will automatically pad the shorter `Morphism` with an identity (a wait) to ensure both have the same duration.

## Usage Example

Here is a conceptual example of how to use `catseq` to build a simple sequence.

First, you import the necessary components:

```python
from catseq.morphism import Morphism, from_atomic, identity
from catseq.hardware.ttl import ttl_on, ttl_off
from catseq.compilation.compiler import compile_to_oasm_calls
from catseq.types.common import Board, Channel
from catseq.types.ttl import TTLState

# Define your hardware channels
board = Board("main_board")
ttl0 = Channel(board, local_id=0, global_id="ttl0")
ttl1 = Channel(board, local_id=1, global_id="ttl1")
```

Next, you can define atomic operations and wrap them in `Morphism`s:

```python
# A 10 microsecond pulse on ttl0
pulse_ttl0 = from_atomic(ttl_on(ttl0, duration_us=10))

# A 5 microsecond pulse on ttl1
pulse_ttl1 = from_atomic(ttl_on(ttl1, duration_us=5))

# A 20 microsecond wait
wait_20us = identity(duration_us=20)
```

Now, you can compose these simple `Morphism`s into a more complex sequence:

```python
# Run the two pulses in parallel.
# `catseq` will automatically add a 5us wait to the ttl1 lane
# to make the durations match.
parallel_pulses = pulse_ttl0 | pulse_ttl1

# Create a sequence: pulse ttl0, wait 20us, then pulse ttl1
sequence = pulse_ttl0 >> wait_20us >> from_atomic(ttl_on(ttl1, duration_us=5))
```

Finally, you can compile the `Morphism` to generate the OASM calls:

```python
# Compile the parallel pulse sequence
oasm_calls = compile_to_oasm_calls(parallel_pulses)

# The `oasm_calls` variable now holds a list of instructions
# that can be compiled into an RTMQ binary.
print(oasm_calls)
```
