# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

### Environment Setup
```bash
# Create virtual environment (using uv for fast package management)
uv venv

# Activate virtual environment (Linux/macOS)
source .venv/bin/activate

# Install in editable mode with dev dependencies
uv pip install -e .[dev]
```

### Code Quality Checks
```bash
# Linting with ruff
ruff check .

# Type checking with mypy (must pass)
mypy .

# Run unit tests (must pass)
pytest

# Run specific test directory
pytest tests/states/ -v

# Run tests with verbose output
pytest -v

# CRITICAL: All three checks (ruff, mypy, pytest) must pass for any code changes
```

### Formatting
```bash
# Format code with ruff
ruff format .
```

## Architecture Overview

Cat-SEQ is a Python framework for quantum physics experiment control based on Category Theory (Monoidal Categories). The current architecture follows the FRAMEWORK_DESIGN.md specifications with a clean layered structure:

### Core System (Primary Implementation)

**Layer 0: Core Protocols** (`catseq/core/protocols.py`)
- Defines base `State` class and `Channel` singleton implementation
- `HardwareDevice` protocol for validation
- Foundation layer with no internal dependencies

**Layer 1: Objects and Morphisms** (`catseq/core/objects.py`, `catseq/core/morphisms.py`)
- `objects.py`: Implements `SystemState` as Category Theory objects
- `morphisms.py`: Implements unified `Morphism` class and `AtomicOperation`
- Core logic for serial (`@`) and parallel (`|`) composition

**Layer 2: States and Hardware** (`catseq/states/`, `catseq/hardware/`)
- Simplified state definitions following framework design
- Hardware device classes for validation and constraints
- Clean separation between state data and device behavior

**Layer 3: Factory Functions** (`catseq/morphisms/`) - *Planned*
- Factory functions for creating morphism builders
- High-level API for experiment sequences

### Key Design Patterns

**Monoidal Category Structure:**
- **Objects**: Complete system state at a moment in time (tuple of channel-state pairs)
- **Morphisms**: Physical processes that evolve system over time
- **Composition**: `@` for serial (sequential), `|` for parallel (simultaneous)

**Deferred Execution Pattern:**
```python
# Define reusable "recipes" (MorphismBuilder objects)
pulse_def = ttl.pulse(duration=10e-6)
wait_def = hold(duration=5e-3)

# Compose abstract sequences
sequence_def = pulse_def @ wait_def @ pulse_def

# Execute on concrete hardware channel
ttl0 = Channel("TTL_0", TTLDevice)
concrete_sequence = sequence_def(ttl0)  # Returns LaneMorphism
```

**Automatic Synchronization:**
- All parallel operations (`|`) automatically synchronize to equal duration
- Framework inserts waits/holds where necessary
- `LaneMorphism` guarantees all lanes have identical total duration

### Project Structure

```
catseq/
├── core/             # Core system implementation (primary)
│   ├── protocols.py  # Base State, Channel, HardwareDevice
│   ├── objects.py    # SystemState (Category objects)
│   └── morphisms.py  # Morphism, AtomicOperation (Category morphisms)
├── states/           # Hardware state definitions
│   ├── ttl.py       # TTL states (TTLOn, TTLOff, TTLInput)
│   ├── rwg.py       # RWG states (RWGUninitialized, RWGReady, RWGActive)
│   ├── dac.py       # DAC states
│   └── common.py    # Common states (Uninitialized)
├── hardware/         # Hardware device classes (legacy system)
├── morphisms/        # Factory functions (planned)
└── FRAMEWORK_DESIGN.md # Complete system design documentation
```

### Important Implementation Details

**Channel Singleton Pattern:**
- `Channel` class uses `__new__` to ensure one instance per name
- Prevents accidental channel duplication

**State Validation:**
- Hardware classes implement `validate_transition()` for state change validation
- Framework enforces physical constraints at composition time

**Type Safety:**
- Uses concrete `Channel` base class instead of generics for better type inference
- `frozen=True` dataclasses ensure immutability

**Testing Structure:**
- **CRITICAL REQUIREMENT**: Test directory structure must mirror catseq directory structure exactly
- Tests for `catseq/core/` go in `tests/core/`
- Tests for `catseq/states/` go in `tests/states/`
- Tests for `catseq/hardware/` go in `tests/hardware/`
- **CRITICAL REQUIREMENT**: All code changes must pass `pytest` tests before being considered complete
- Every new module or significant change must have corresponding pytest tests
- Tests must cover functionality, edge cases, type safety, and immutability
- Comprehensive test coverage across all layers
- Use cases in `tests/use_cases/` demonstrate real experiment patterns

**Python Version Requirements:**
- Uses Python 3.12.11 with uv virtual environment
- No `from __future__ import annotations` needed
- Uses modern typing features: `Self`, built-in generics (`list[T]`, `dict[K, V]`)
- Strict type safety: no `Any` types or `# type: ignore` comments allowed

## Development Notes

- The project uses `uv` for fast package management
- Code must pass ruff linting, mypy type checking, and pytest tests
- Framework is designed for RTMQ hardware ecosystem but core is hardware-agnostic
- Compiler component (`compiler.py`) is planned but not yet implemented
- Documentation includes detailed Chinese technical specifications in `DEVDOC.md`