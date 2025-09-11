"""
CatSeq: Category Theory-based Quantum Experiment Sequencing

A Python framework for quantum physics experiment control based on 
Category Theory (Monoidal Categories). CatSeq provides a mathematical
foundation for composing complex quantum control sequences with 
precise timing and state management.

Core concepts:
- Morphisms: Physical processes that evolve the system over time
- Composition: @ (strict state matching), >> (auto state inference), | (parallel)
- OASM Interface: Translation to hardware control via OASM DSL
"""

# Core types and enums


# Time utilities
from .time_utils import us_to_cycles, cycles_to_us

# Atomic operations
from .atomic import ttl_init, ttl_on, ttl_off
from .morphism import identity

# Morphism system
from .morphism import Morphism, from_atomic

# Hardware abstraction
from .hardware import pulse, initialize, set_high, set_low, hold

# OASM interface
from .compilation import compile_to_oasm_calls, execute_oasm_calls, OASMCall

__version__ = "0.1.0"

__all__ = [
    # Core types
    # 'Board',
    # 'Channel', 
    # 'TTLState',
    # 'OperationType',
    # 'AtomicMorphism',
    
    # Time utilities
    'us_to_cycles',
    'cycles_to_us',
    
    # Atomic operations
    'ttl_init',
    'ttl_on', 
    'ttl_off',
    'identity',
    
    # Morphism system
    'Morphism',
    'from_atomic',
    
    # Hardware abstraction
    'pulse',
    'initialize_channel',
    'set_high',
    'set_low', 
    'hold',
    
    # OASM interface
    'compile_to_oasm_calls',
    'execute_oasm_calls',
    'OASMCall',
]