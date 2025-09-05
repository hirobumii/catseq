# CatSeq

![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Version](https://img.shields.io/badge/version-0.2.0-orange.svg)
![Tests](https://img.shields.io/badge/tests-49%20passed-brightgreen.svg)

> **A Category Theory-based framework for quantum experiment sequencing** - A mathematically rigorous abstraction for hardware timing in quantum physics experiments.

<p align="center">
  <a href="docs/user/01_quickstart.md"><strong>Quickstart</strong></a> ·
  <a href="docs/user/02_core_concepts.md"><strong>Core Concepts</strong></a> ·
  <a href="docs/dev/compiler_notes.md">Developer Docs</a> ·
  <a href="https://github.com/hirobumii/catseq/issues">Report a Bug</a>
</p>

---

## Table of Contents

- [Introduction](#introduction)
- [Core Features](#core-features)
- [Quickstart](#quickstart)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Basic Usage](#basic-usage)
- [Design Philosophy](#design-philosophy)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgements](#acknowledgements)

## Introduction

**CatSeq** (Category Theory-based Quantum Experiment Sequencing) is a hardware control framework designed specifically for quantum physics experiments. It is built upon the mathematical principles of **Monoidal Categories** to provide a rigorous foundation and an intuitive programming abstraction for complex quantum control sequences.

In traditional quantum experiment control, coordinating complex timing, managing state, and handling parallel operations often leads to code that is difficult to understand and maintain. CatSeq abstracts these complexities into predictable and verifiable mathematical objects by leveraging the **compositionality** and **type safety** of category theory, making quantum experiment programming both intuitive and powerful.

This framework is particularly well-suited for quantum physics research teams that require **precise timing control** (nanosecond-level precision), **multi-channel coordination**, and **complex waveform synthesis**.

## Core Features

* **🧮 Mathematical Rigor**: Based on Monoidal Category theory, providing provably correct operational compositions.
* **⚡ Precise Timing**: Supports 250MHz clock resolution (4ns), meeting the strict timing requirements of quantum experiments.
* **🔀 Flexible Composition**: Intuitive sequence composition using the `@` (serial) and `|` (parallel) operators.
* **🎛️ Multi-Hardware Support**: Unified control over various quantum experiment hardware, such as TTL switches and AWG waveform generators.
* **🔧 Type Safety**: Compile-time state verification to prevent hardware configuration errors and timing conflicts.
* **⚙️ OASM Compilation**: Directly compiles to RTMQ hardware instructions, eliminating the need to write low-level assembly code by hand.

## Quickstart

### Prerequisites

Before you begin, ensure you have the following software installed in your development environment:
* [Python](https://python.org/) (version >= 3.12)
* [uv](https://docs.astral.sh/uv/) A modern Python package manager

### Installation

**Option 1: Using the provided setup script (Recommended)**
```bash
git clone [https://github.com/hirobumii/catseq.git](https://github.com/hirobumii/catseq.git)
cd catseq
chmod +x setup.sh
./setup.sh
```

**Option 2: Manual Installation**
```bash
# 1. Clone the repository
git clone [https://github.com/hirobumii/catseq.git](https://github.com/hirobumii/catseq.git)
cd catseq

# 2. Install uv (if not already installed)
curl -LsSf [https://astral.sh/uv/install.sh](https://astral.sh/uv/install.sh) | sh

# 3. Create a virtual environment and install dependencies
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .[dev]

# 4. Verify the installation
.venv/bin/pytest tests/ -v
```

### Basic Usage

Here is a basic example of creating a TTL pulse sequence:

```python
from catseq import ttl_init, ttl_on, ttl_off, identity
from catseq.types.common import Board, Channel, ChannelType
from catseq.compilation import compile_to_oasm_calls

# Define hardware channels
board = Board("RWG_0")
ttl_ch = Channel(board, 0, ChannelType.TTL)

# Build the sequence: initialize -> on for 10μs -> off
pulse_sequence = (
    ttl_init(ttl_ch) @ 
    ttl_on(ttl_ch) @ 
    identity(ttl_ch, 10e-6) @ 
    ttl_off(ttl_ch)
)

# Compile to hardware instructions
oasm_calls = compile_to_oasm_calls(pulse_sequence)

# Execute the sequence (requires RTMQ hardware environment)
# execute_oasm_calls(oasm_calls)
```

**Example of parallel operations**:
```python
# Create pulses on two different channels
ch1_pulse = ttl_on(ch1) @ identity(ch1, 5e-6) @ ttl_off(ch1)
ch2_pulse = ttl_on(ch2) @ identity(ch2, 8e-6) @ ttl_off(ch2)

# Execute in parallel (time is automatically aligned)
parallel_sequence = ch1_pulse | ch2_pulse  # Total duration will be 8μs
```

For more advanced usage and AWG waveform control, please refer to our [Quickstart Guide](docs/user/01_quickstart.md).

## Design Philosophy

The design of CatSeq is based on the following core principles:

### 🧮 Category Theory Foundation
- **Objects**: The complete state of the system (a mapping of all channel states).
- **Morphisms**: Physical processes (state transitions that evolve over time).
- **Composition**: Strict function composition that guarantees state continuity.

### 🔒 Type Safety First
- Compile-time state verification to prevent illegal state transitions.
- Strongly-typed channel management to avoid hardware address errors.
- Automatic inference of state transitions to reduce manual errors.

### 🎯 User-Friendliness
- Intuitive operators: `@` for sequential composition and `|` for parallel execution.
- A declarative programming style that focuses on "what to do" rather than "how to do it."
- Rich error messages and debugging information.

## Roadmap

We have a clear plan for the future development of CatSeq:

**v0.2.0** (Q2 2025)
- [ ] **Visualization Tools**: Timing diagram generation and an interactive debugging interface.
- [ ] **Broader Hardware Support**: Support for more types of quantum experiment devices.
- [ ] **Performance Optimization**: Compilation optimizations for large-scale sequences.

**v0.3.0** (Q3 2025)
- [ ] **Cloud Compilation**: Support for real-time control of remote hardware.
- [ ] **Machine Learning Integration**: Automated parameter optimization and sequence learning.
- [ ] **Standard Library Expansion**: A pre-defined library of common quantum experiment operations.

Feel free to check out our [Issues](https://github.com/hirobumii/catseq/issues) page for more details and to join the discussion.

## Contributing

We welcome contributions from the community! If you'd like to get involved, please follow these steps:

1.  Fork the repository
2.  Create your feature branch (`git checkout -b feature/AmazingFeature`)
3.  Run tests to ensure code quality (`.venv/bin/pytest tests/ -v`)
4.  Commit your changes (`git commit -m 'Add some AmazingFeature'`)
5.  Push to the branch (`git push origin feature/AmazingFeature`)
6.  Open a Pull Request

**Development Environment Setup**:
```bash
# Use the script for a quick setup
./setup.sh

# Or set up manually
source .venv/bin/activate
uv pip install -e .[dev]

# Run the test suite
.venv/bin/pytest tests/ -v

# Check code formatting and types
ruff check catseq/
mypy catseq/
```
Before contributing, please be sure to run the test suite to ensure all 49 tests are passing.

## License

This project is distributed under the **MIT** License. See the `LICENSE` file for more information.

## Acknowledgements

- **Foundations of Category Theory**: Our thanks to the mathematicians whose work on Monoidal Category theory made this possible.
- **RTMQ Hardware Platform**: For providing a powerful hardware foundation for quantum experiment control.
- **The Python Ecosystem**: Excellent tools like NumPy, pytest, and uv make development efficient.
- **uv Package Manager**: For providing fast and reliable dependency management for the project.

---

<p align="center">
  <strong>CatSeq - Bringing mathematical elegance to quantum experiment control.</strong>
</p>