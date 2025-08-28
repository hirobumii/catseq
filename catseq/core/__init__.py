"""
CatSeq核心模块
基于范畴论的量子实验控制框架
"""

from .protocols import (
    State,
    Channel,
    HardwareDevice,
    PhysicsViolationError,
    CompositionError,
    CompilerError
)

from .objects import (
    SystemState,
    SystemStateBuilder,
    create_system_state
)

from .morphisms import (
    AtomicOperation,
    Morphism
)

__all__ = [
    # 基础协议
    'State',
    'Channel', 
    'HardwareDevice',
    'PhysicsViolationError',
    'CompositionError',
    'CompilerError',
    
    # 对象系统
    'SystemState',
    'SystemStateBuilder',
    'create_system_state',
    
    # Morphism系统
    'AtomicOperation',
    'Morphism'
]