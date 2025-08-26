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

# Type checking with mypy
mypy .

# Run unit tests
pytest

# Run specific test file
pytest tests/test_model.py

# Run tests with verbose output
pytest -v
```

### Formatting
```bash
# Format code with ruff
ruff format .
```

## Architecture Overview

Cat-SEQ is a Python framework for quantum physics experiment control based on Category Theory (Monoidal Categories). The codebase follows a layered architecture with clear separation of concerns:

### Core Layers (Bottom to Top)

**Layer 0: Core Protocols** (`catseq/protocols.py`)
- Defines abstract base classes: `State`, `Channel`, `HardwareInterface`
- Foundation layer with no internal dependencies
- All other modules depend on this layer

**Layer 1: Algebraic Engine** (`catseq/model.py`, `catseq/builder.py`)
- `model.py`: Implements `PrimitiveMorphism` and `LaneMorphism` with composition operators (`@`, `|`)
- `builder.py`: Implements `MorphismBuilder` for deferred execution patterns
- Core logic for composing and building morphisms

**Layer 2: Hardware Vocabulary** (`catseq/hardware/`, `catseq/states/`)
- Generic hardware device definitions (`TTLDevice`, `RWGDevice`)
- State definitions (`TTLState`, `RWGActive`, etc.)
- Hardware validation rules and state transitions

**Layer 3: Morphism API** (`catseq/morphisms/`)
- Factory functions for creating `MorphismBuilder` objects
- Convenient functions like `ttl.pulse()`, `rwg.linear_ramp()`, `common.hold()`

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
├── protocols.py      # Core abstractions (no internal deps)
├── model.py          # LaneMorphism, PrimitiveMorphism, composition logic  
├── builder.py        # MorphismBuilder for deferred execution
├── pending.py        # State inference for compositional morphisms
├── hardware/         # Hardware device classes and validation
├── states/           # State definitions for different hardware types
├── morphisms/        # Factory functions returning MorphismBuilder objects
└── ARCHITECTURE.md   # Detailed design documentation (in Chinese)
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
- Test fixtures in `tests/conftest.py` provide standard channel instances
- Comprehensive test coverage across all layers
- Use cases in `tests/use_cases/` demonstrate real experiment patterns

## Development Notes

- The project uses `uv` for fast package management
- Code must pass ruff linting, mypy type checking, and pytest tests
- Framework is designed for RTMQ hardware ecosystem but core is hardware-agnostic
- Compiler component (`compiler.py`) is planned but not yet implemented
- Documentation includes detailed Chinese technical specifications in `DEVDOC.md`