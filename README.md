# CatSeq

![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Version](https://img.shields.io/badge/version-0.2.1-orange.svg)
![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)

> **A Category Theory-based framework for quantum experiment sequencing** - A mathematically rigorous abstraction for hardware timing in quantum physics experiments, powered by xDSL/MLIR compiler infrastructure.

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

**CatSeq** (Category Theory-based Quantum Experiment Sequencing) is a hardware control framework designed specifically for quantum physics experiments. Built on **Monoidal Category** theory and **xDSL/MLIR** compiler infrastructure, it provides both mathematical rigor and practical performance for complex quantum control sequences.

CatSeq offers **two programming interfaces**:
- **Morphism API**: Low-level hardware control with category theory semantics (`@`, `|`, `>>` operators)
- **Program API**: High-level functional programming with Haskell-style monads (`execute`, `seq`, `repeat`, `cond`)

The framework features a **non-recursive compiler** that handles unlimited nesting depth and compiles directly to RTMQ hardware instructions, making quantum experiment programming both mathematically rigorous and practically efficient.

## Core Features

* **🧮 Mathematical Rigor**: Based on Monoidal Category theory, providing provably correct operational compositions.
* **⚡ Precise Timing**: Supports 250MHz clock resolution (4ns), meeting the strict timing requirements of quantum experiments.
* **🔀 Flexible Composition**: Two APIs - Morphism operators (`@`, `|`, `>>`) and functional combinators (`seq`, `repeat`, `cond`).
* **🎛️ Multi-Hardware Support**: Unified control over various quantum experiment hardware, such as TTL switches and AWG waveform generators.
* **🔧 Type Safety**: Compile-time state verification to prevent hardware configuration errors and timing conflicts.
* **⚙️ OASM Compilation**: Directly compiles to RTMQ hardware instructions via xDSL/MLIR compiler infrastructure.
* **♾️ Unlimited Nesting**: Non-recursive compiler design handles 10,000+ nested operations without stack overflow.

## Quickstart

### Prerequisites

Before you begin, ensure you have the following software installed in your development environment:
* [Python](https://python.org/) (version >= 3.12)
* [uv](https://docs.astral.sh/uv/) A modern Python package manager

### Installation

**Linux/macOS - Using setup script (Recommended)**
```bash
git clone https://github.com/hirobumii/catseq.git
cd catseq
chmod +x scripts/setup.sh
./scripts/setup.sh
```

**Windows PowerShell - Using setup script (Recommended)**
```powershell
git clone https://github.com/hirobumii/catseq.git
cd catseq
.\scripts\setup.ps1
```

**Manual Installation (Any Platform)**
```bash
# 1. Clone the repository
git clone https://github.com/hirobumii/catseq.git
cd catseq

# 2. Install uv (if not already installed)
# Linux/macOS:
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows PowerShell:
# Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression

# 3. Create a virtual environment and install dependencies
uv venv --python 3.12
# Linux/macOS:
source .venv/bin/activate
# Windows:
# .\.venv\Scripts\Activate.ps1

uv pip install -e .[dev]

# 4. Verify the installation
.venv/bin/pytest tests/ -v  # Linux/macOS
# .\.venv\Scripts\python.exe -m pytest tests/ -v  # Windows
```

**Install from Any Location**

To install CatSeq as a dependency from any directory:

```bash
# Option 1: Direct installation (requires OASM.dev pre-installed)
pip install oasm.dev h5py scipy numpy
pip install git+https://github.com/hirobumii/catseq.git

# Option 2: Clone and install with environment auto-detection
git clone https://github.com/hirobumii/catseq.git
cd catseq
python scripts/post_install.py  # Automatically detects your environment
pip install -e .
```

The `post_install.py` script automatically detects your Python environment (virtualenv or system) and installs the required OASM extensions to the correct location.

### Basic Usage

**Morphism API - Category Theory Style:**

```python
from catseq import ttl_init, ttl_on, ttl_off, wait
from catseq.types.common import Board, Channel, ChannelType
from catseq.compilation import compile_to_oasm_calls

# Define hardware
board = Board("RWG_0")
ttl_ch = Channel(board, 0, ChannelType.TTL)

# Build sequence using operators
pulse = (
    ttl_init(ttl_ch) >>      # Auto-inferring composition
    ttl_on(ttl_ch) >>        # State: OFF → ON
    wait(ttl_ch, 10e-6) >>   # Wait 10μs
    ttl_off(ttl_ch)          # State: ON → OFF
)

# Parallel execution on multiple channels
ch1_pulse = ttl_on(ch1) @ wait(ch1, 5e-6) @ ttl_off(ch1)
ch2_pulse = ttl_on(ch2) @ wait(ch2, 8e-6) @ ttl_off(ch2)
parallel = ch1_pulse | ch2_pulse  # Executes simultaneously

# Compile to hardware instructions
oasm_calls = compile_to_oasm_calls(parallel)
```

**Program API - Functional Style:** 🆕

```python
from catseq import execute, seq, repeat, cond, var

# Define pulse as morphism
pulse = ttl_on(ttl_ch) @ wait(ttl_ch, 10e-6) @ ttl_off(ttl_ch)

# Functional composition
program = (
    execute(pulse)                    # Execute once
    >> execute(pulse).replicate(100)  # Repeat 100 times
)

# Runtime conditional execution
adc_value = var("adc_value", "int32")
threshold = 500

conditional = execute(pulse_high).when(adc_value > threshold)

# Multi-way branching
program = cond([
    (adc_value > 1000, execute(pulse_very_high)),
    (adc_value > 500,  execute(pulse_high)),
], default=execute(pulse_low))
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

**Completed:**
- [x] Monoidal Category-based Morphism API
- [x] xDSL/MLIR compiler infrastructure
- [x] Program API (functional programming interface)
- [x] Non-recursive compiler design (unlimited nesting)
- [x] 5-stage compilation pipeline
- [x] Multi-hardware support (TTL, AWG, RF)

**In Progress:**
- [ ] Complete compiler backend (xDSL IR → OASM code generation)
- [ ] Optimization passes (loop unrolling, dead code elimination)
- [ ] Runtime condition support (TCS instruction mapping)

**Future Work:**
- [ ] Enhanced visualization tools (interactive timeline debugger)
- [ ] Performance benchmarks and profiling
- [ ] Cloud compilation and remote hardware control
- [ ] Machine learning integration for sequence optimization
- [ ] Standard library of common quantum operations
- [ ] Broader hardware support

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
# Linux/macOS - Use the setup script
chmod +x scripts/setup.sh && ./scripts/setup.sh

# Windows PowerShell - Use the setup script
.\scripts\setup.ps1

# Or set up manually (any platform)
source .venv/bin/activate  # Linux/macOS
# .\.venv\Scripts\Activate.ps1  # Windows

uv pip install -e .[dev]

# Run the test suite
.venv/bin/pytest tests/ -v  # Linux/macOS
# .\.venv\Scripts\python.exe -m pytest tests/ -v  # Windows

# Check code formatting and types
ruff check catseq/
mypy catseq/
```
Before contributing, please be sure to run the test suite to ensure all tests are passing.

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